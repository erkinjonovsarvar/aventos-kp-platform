-- 0009: Admin tasdiqlangan/yuborilgan KP ni ham BUTUNLAY o'chira oladi (foydalanuvchi qarori 2026-10-15).
-- Xavfsizlik:
--  * O'chirish faqat delete_quotation() orqali. U SECURITY DEFINER (egasi nomidan) va chaqiruvchida
--    kp.delete ruxsati borligini BAZANING O'ZIDA tekshiradi (app.user_id -> v_user_effective_permission).
--  * Qulf triggerlari faqat shu funksiya ichida (current_user <> session_user VA app.kp_delete o'rnatilgan)
--    o'chirishga ruxsat beradi. Oddiy ulanishda (aventos_app) tasdiqlangan KP avvalgidek o'zgarmaydi.
--  * Barcha o'chirilgan qatorlar audit_log ga eski qiymati bilan yoziladi (audit triggerlari ishlab turadi).

CREATE FUNCTION kp_delete_in_progress() RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.kp_delete', true), '') <> '' AND current_user <> session_user;
$$;

CREATE OR REPLACE FUNCTION trg_revision_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' AND NOT kp_delete_in_progress() THEN
            RAISE EXCEPTION USING MESSAGE = 'Faqat qoralama (draft) revisionni o''chirish mumkin', ERRCODE = 'P0001';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'draft' THEN
        RETURN NEW;
    END IF;
    IF (OLD.status, NEW.status) NOT IN (('approved', 'sent'), ('approved', 'cancelled'), ('sent', 'cancelled'))
       OR ROW(NEW.quotation_id, NEW.revision_no, NEW.kp_date, NEW.validity_days, NEW.display_currency,
              NEW.exchange_rate_id, NEW.vat_rate_id, NEW.show_excl_vat_note, NEW.approved_by, NEW.approved_at)
          IS DISTINCT FROM
          ROW(OLD.quotation_id, OLD.revision_no, OLD.kp_date, OLD.validity_days, OLD.display_currency,
              OLD.exchange_rate_id, OLD.vat_rate_id, OLD.show_excl_vat_note, OLD.approved_by, OLD.approved_at) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'KP revisioni ' || OLD.status || ' holatida — o''zgartirish faqat yangi revision orqali',
            ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION trg_annex_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND kp_delete_in_progress() THEN RETURN OLD; END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM assert_revision_editable(OLD.revision_id); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM assert_revision_editable(NEW.revision_id); END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE OR REPLACE FUNCTION trg_by_annex_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND kp_delete_in_progress() THEN RETURN OLD; END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM assert_revision_editable(revision_of_annex(OLD.annex_id)); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM assert_revision_editable(revision_of_annex(NEW.annex_id)); END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE OR REPLACE FUNCTION trg_by_line_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND kp_delete_in_progress() THEN RETURN OLD; END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM assert_revision_editable(revision_of_line(OLD.line_id)); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM assert_revision_editable(revision_of_line(NEW.line_id)); END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE FUNCTION delete_quotation(p_kp_number bigint) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_actor bigint := nullif(current_setting('app.user_id', true), '')::bigint;
    v_q bigint;
    v_revisions integer;
BEGIN
    IF v_actor IS NULL OR NOT EXISTS (
            SELECT 1 FROM v_active_user a JOIN v_user_effective_permission p ON p.user_id = a.user_id
            WHERE a.user_id = v_actor AND p.permission_code = 'kp.delete') THEN
        RAISE EXCEPTION USING MESSAGE = 'KP ni faqat admin o''chira oladi (kp.delete)', ERRCODE = '42501';
    END IF;
    SELECT id INTO v_q FROM quotation WHERE kp_number = p_kp_number;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING MESSAGE = 'KP topilmadi', ERRCODE = 'P0002';
    END IF;
    PERFORM set_config('app.kp_delete', p_kp_number::text, true);
    SELECT count(*) INTO v_revisions FROM quotation_revision WHERE quotation_id = v_q;
    DELETE FROM quotation_line WHERE annex_id IN (
        SELECT a.id FROM quotation_annex a JOIN quotation_revision r ON r.id = a.revision_id WHERE r.quotation_id = v_q);
    DELETE FROM quotation_annex WHERE revision_id IN (SELECT id FROM quotation_revision WHERE quotation_id = v_q);
    DELETE FROM quotation_revision WHERE quotation_id = v_q;
    DELETE FROM quotation WHERE id = v_q;
    PERFORM set_config('app.kp_delete', '', true);
    RETURN v_revisions;
END $$;

REVOKE ALL ON FUNCTION delete_quotation(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_quotation(bigint) TO aventos_app;
