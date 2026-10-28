-- 0028: Tayyor (tasdiqlangan/yuborilgan) KP ning valyutasini (USD <-> UZS) shu revisionning o'zida almashtirish
--   (foydalanuvchi qarori 2026-10-28: "Valyutani ham tayyor KP da o'zgartirish mumkin bo'lishi kerak";
--    revision raqami o'zgarmaydi, qayta tasdiqlanmaydi; kim almashtira oladi — kp.approve; kurs har safar
--    tasdiqlangan kurslar ro'yxatidan tanlanadi).
-- Xavfsizlik (0009 delete_quotation() kabi):
--  * Almashtirish faqat change_revision_currency() orqali. U SECURITY DEFINER va ruxsatni BAZANING O'ZIDA tekshiradi
--    (app.user_id -> v_user_effective_permission): qoralama — kp.create_edit yoki kp.approve, tayyor KP — kp.approve.
--  * Qulf triggeri tayyor revisionda faqat shu funksiya ichida (current_user <> session_user VA app.kp_currency_change =
--    revision id) va faqat display_currency / exchange_rate_id ni o'zgartirishga ruxsat beradi; boshqa ustunlar,
--    qatorlar, chegirmalar avvalgidek qulf.
--  * Har almashtirish revision_currency_change ga yoziladi (kim, qachon, eski va yangi valyuta/kurs, o'sha paytdagi holat);
--    jadval faqat qo'shiladi (KP butunlay o'chirilgandagina birga o'chadi). quotation_revision dagi audit triggeri ham yozadi.
--  * Narxlar o'zgarmaydi — v_line_price ko'rinish valyutasini revisiondan oladi (USD -> UZS: × tanlangan kurs).
--    Summa ko'rinishidagi mahsulot chegirmasi (line_discount.kind = 'amount', KP valyutasida) bor bo'lsa yoki
--    yangi valyutada narxi chiqmaydigan qator paydo bo'lsa — almashtirilmaydi (taxmin qilinmaydi).

CREATE TABLE revision_currency_change (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    revision_id      bigint NOT NULL REFERENCES quotation_revision(id) ON DELETE CASCADE,
    status_at_change text NOT NULL,
    old_currency     char(3) NOT NULL REFERENCES currency(code),
    old_rate_id      bigint REFERENCES exchange_rate(id),
    new_currency     char(3) NOT NULL REFERENCES currency(code),
    new_rate_id      bigint REFERENCES exchange_rate(id),
    changed_by       bigint NOT NULL REFERENCES app_user(id),
    changed_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (new_currency <> 'UZS' OR new_rate_id IS NOT NULL)
);
COMMENT ON TABLE revision_currency_change IS 'KP revisioni valyutasi/kursi almashtirilgan tarix (0028); faqat qo''shiladi';
CREATE INDEX ON revision_currency_change (revision_id);

CREATE FUNCTION kp_currency_change_in_progress(p_revision_id bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.kp_currency_change', true), '') = p_revision_id::text
           AND current_user <> session_user;
$$;

CREATE FUNCTION trg_currency_change_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND kp_delete_in_progress() THEN RETURN OLD; END IF;
    RAISE EXCEPTION USING MESSAGE = 'Valyuta almashtirish tarixi faqat qo''shiladi: ' || TG_OP || ' taqiqlangan', ERRCODE = 'P0001';
END $$;
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON revision_currency_change
    FOR EACH ROW EXECUTE FUNCTION trg_currency_change_append_only();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON revision_currency_change FOR EACH ROW EXECUTE FUNCTION trg_audit();

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
    -- 0028: change_revision_currency() ichida — faqat valyuta va kurs almashadi, qolgani aynan o'sha
    IF kp_currency_change_in_progress(OLD.id) AND NEW.status = OLD.status
       AND ROW(NEW.quotation_id, NEW.revision_no, NEW.kp_date, NEW.validity_days, NEW.vat_rate_id,
               NEW.show_excl_vat_note, NEW.approved_by, NEW.approved_at)
           IS NOT DISTINCT FROM
           ROW(OLD.quotation_id, OLD.revision_no, OLD.kp_date, OLD.validity_days, OLD.vat_rate_id,
               OLD.show_excl_vat_note, OLD.approved_by, OLD.approved_at) THEN
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

CREATE FUNCTION change_revision_currency(p_revision_id bigint, p_currency text, p_rate_id bigint) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_actor bigint := nullif(current_setting('app.user_id', true), '')::bigint;
    v_old quotation_revision;
    v_missing_before integer;
    v_missing_after integer;
    v_id bigint;
BEGIN
    SELECT * INTO v_old FROM quotation_revision WHERE id = p_revision_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING MESSAGE = 'KP revisioni topilmadi', ERRCODE = 'P0002';
    END IF;
    IF v_actor IS NULL OR NOT EXISTS (
            SELECT 1 FROM v_active_user a JOIN v_user_effective_permission p ON p.user_id = a.user_id
            WHERE a.user_id = v_actor AND (p.permission_code = 'kp.approve'
                  OR (v_old.status = 'draft' AND p.permission_code = 'kp.create_edit'))) THEN
        RAISE EXCEPTION USING MESSAGE = 'Tayyor KP ning valyutasini faqat KP ni tasdiqlay oladigan xodim almashtiradi (kp.approve)',
                              ERRCODE = '42501';
    END IF;
    IF v_old.status = 'cancelled' THEN
        RAISE EXCEPTION USING MESSAGE = 'Bekor qilingan KP ning valyutasi almashtirilmaydi', ERRCODE = 'P0001';
    END IF;
    IF p_currency NOT IN ('USD', 'UZS') THEN
        RAISE EXCEPTION USING MESSAGE = 'Valyuta faqat USD yoki UZS', ERRCODE = '22023';
    END IF;
    IF p_currency = 'USD' THEN
        p_rate_id := NULL;
    ELSIF p_rate_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM exchange_rate WHERE id = p_rate_id AND from_currency = 'USD' AND to_currency = 'UZS') THEN
        RAISE EXCEPTION USING MESSAGE = 'UZS uchun tasdiqlangan kursni tanlang (USD -> UZS)', ERRCODE = '22023';
    END IF;
    IF v_old.display_currency = p_currency AND v_old.exchange_rate_id IS NOT DISTINCT FROM p_rate_id THEN
        RAISE EXCEPTION USING MESSAGE = 'KP allaqachon shu valyuta va kursda', ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM line_discount d JOIN quotation_line l ON l.id = d.line_id
               JOIN quotation_annex a ON a.id = l.annex_id
               WHERE a.revision_id = p_revision_id AND d.kind = 'amount') THEN
        RAISE EXCEPTION USING
            MESSAGE = 'KP da summa ko''rinishidagi mahsulot chegirmasi bor (' || v_old.display_currency
                      || ' da) — valyuta almashtirilmaydi: summa avtomatik qayta hisoblanmaydi',
            ERRCODE = 'P0001';
    END IF;
    SELECT count(*) INTO v_missing_before FROM v_line_price WHERE revision_id = p_revision_id AND display_line_total IS NULL;

    PERFORM set_config('app.kp_currency_change', p_revision_id::text, true);
    UPDATE quotation_revision SET display_currency = p_currency, exchange_rate_id = p_rate_id WHERE id = p_revision_id;
    PERFORM set_config('app.kp_currency_change', '', true);

    SELECT count(*) INTO v_missing_after FROM v_line_price WHERE revision_id = p_revision_id AND display_line_total IS NULL;
    IF v_missing_after > v_missing_before THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Ba''zi qatorlar narxi ' || p_currency || ' ga o''tkazilmaydi (narx boshqa valyutada) — valyuta almashtirilmadi',
            ERRCODE = 'P0001';
    END IF;
    INSERT INTO revision_currency_change (revision_id, status_at_change, old_currency, old_rate_id, new_currency, new_rate_id, changed_by)
    VALUES (p_revision_id, v_old.status, v_old.display_currency, v_old.exchange_rate_id, p_currency, p_rate_id, v_actor)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

REVOKE ALL ON FUNCTION change_revision_currency(bigint, text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION change_revision_currency(bigint, text, bigint) TO aventos_app;
