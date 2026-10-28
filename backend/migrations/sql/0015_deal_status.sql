-- 0015: KP savdo holati (foydalanuvchi qarori 2026-10-16). Menejer o'z KP siga holat belgilaydi:
--   Jarayonda / Sotildi (summa, valyuta, sana majburiy) / Yutqazildi (sabab + izoh majburiy) / Loyiha yopildi (izoh ixtiyoriy).
-- Har o'zgarish tarix sifatida saqlanadi (faqat qo'shiladi); joriy holat = oxirgi yozuv (v_quotation_deal).
-- Mavjud KP larga holat berilmaydi ("belgilanmagan") — menejerga eslatma chiqadi.
-- Ruxsatlar: deal.update (menejer roli), dashboard.view (admin roli; boshqalarga admin alohida beradi).

INSERT INTO permission (code, name, description) VALUES
    ('deal.update', 'KP savdo holatini belgilash', 'Faqat o''zi menejer bo''lgan KP lar uchun'),
    ('dashboard.view', 'Dashboard (hisobotlar)', 'Menejer faqat o''z ko''rsatkichlarini, barcha KP ruxsati borlar hammasini ko''radi');
INSERT INTO role_permission (role_code, permission_code) VALUES ('manager', 'deal.update'), ('admin', 'dashboard.view');

CREATE TABLE deal_status (
    code          text PRIMARY KEY,
    name          text NOT NULL,
    sort_order    integer NOT NULL UNIQUE
);
INSERT INTO deal_status (code, name, sort_order) VALUES
    ('in_progress', 'Jarayonda', 1), ('won', 'Sotildi', 2), ('lost', 'Yutqazildi', 3), ('closed', 'Loyiha yopildi', 4);

CREATE TABLE lost_reason (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    sort_order  integer NOT NULL UNIQUE
);
INSERT INTO lost_reason (code, name, sort_order) VALUES
    ('price', 'Narx qimmat', 1), ('competitor', 'Raqobatchi tanlandi', 2), ('timing', 'Muddat to''g''ri kelmadi', 3),
    ('cancelled', 'Loyiha bekor qilindi', 4), ('other', 'Boshqa', 5);

CREATE TABLE quotation_deal_event (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quotation_id      bigint NOT NULL REFERENCES quotation(id),
    status_code       text NOT NULL REFERENCES deal_status(code),
    sold_amount       numeric CHECK (sold_amount > 0),              -- QQS bilan, sold_currency da
    sold_currency     char(3) REFERENCES currency(code),
    sold_on           date,
    lost_reason_code  text REFERENCES lost_reason(code),
    comment           text,
    created_by        bigint NOT NULL REFERENCES app_user(id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK ((status_code = 'won') = (sold_amount IS NOT NULL AND sold_currency IS NOT NULL AND sold_on IS NOT NULL)),
    CHECK (status_code = 'won' OR (sold_amount IS NULL AND sold_currency IS NULL AND sold_on IS NULL)),
    CHECK ((status_code = 'lost') = (lost_reason_code IS NOT NULL)),
    CHECK (status_code <> 'lost' OR btrim(coalesce(comment, '')) <> '')
);
CREATE INDEX ix_deal_event_quotation ON quotation_deal_event (quotation_id, created_at DESC, id DESC);

-- Tarix o'zgarmaydi; faqat admin KP ni butunlay o'chirganda (delete_quotation) birga o'chadi
CREATE FUNCTION trg_deal_event_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND kp_delete_in_progress() THEN RETURN OLD; END IF;
    RAISE EXCEPTION USING MESSAGE = 'Savdo holati tarixi faqat qo''shiladi: ' || TG_OP || ' taqiqlangan', ERRCODE = 'P0001';
END $$;
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON quotation_deal_event FOR EACH ROW EXECUTE FUNCTION trg_deal_event_append_only();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation_deal_event FOR EACH ROW EXECUTE FUNCTION trg_audit();

CREATE VIEW v_quotation_deal AS
SELECT DISTINCT ON (e.quotation_id)
       e.quotation_id, e.id AS event_id, e.status_code, s.name AS status_name, e.sold_amount, e.sold_currency, e.sold_on,
       e.lost_reason_code, lr.name AS lost_reason_name, e.comment, e.created_by, e.created_at
FROM quotation_deal_event e
JOIN deal_status s ON s.code = e.status_code
LEFT JOIN lost_reason lr ON lr.code = e.lost_reason_code
ORDER BY e.quotation_id, e.created_at DESC, e.id DESC;

-- KP ni butunlay o'chirish savdo tarixini ham o'chiradi
CREATE OR REPLACE FUNCTION delete_quotation(p_kp_number bigint) RETURNS integer
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
    DELETE FROM quotation_deal_event WHERE quotation_id = v_q;
    DELETE FROM quotation WHERE id = v_q;
    PERFORM set_config('app.kp_delete', '', true);
    RETURN v_revisions;
END $$;
