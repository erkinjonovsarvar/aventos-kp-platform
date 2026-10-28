-- 0022 (2026-10-20, Phase 4 xavfsizlik va ma'lumot sifati). Mavjud ma'lumot O'ZGARMAYDI.
--
-- 1) Audit jurnaliga maxfiy hash'lar yozilmaydi: password_hash (avvaldan) + admin_word_hash, token_hash, code_hash.
--    Eski audit_log yozuvlari append-only — ularga tegilmaydi (qaror: PHASE_2_BLOCKERS B7).
-- 2) Login katta-kichik harfdan qat'i nazar yagona: "Admin" va "admin" ikki xil foydalanuvchi bo'la olmaydi.
--    (Dastur loginni lower() bilan qidiradi; avval cheklov faqat aniq yozilishga edi.)
-- 3) Bo'sh nomli yangi loyiha/ilova qo'shilmaydi. Loyiha uchun NOT VALID: bazadagi 17 ta bo'sh nomli eski loyiha
--    hozircha qoladi (ular haqida qaror — foydalanuvchida), yangi va o'zgartirilgan qatorlar tekshiriladi.

CREATE OR REPLACE FUNCTION trg_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_user bigint := nullif(current_setting('app.user_id', true), '')::bigint;
    v_old jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
    v_new jsonb := CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN to_jsonb(NEW) END;
    v_key text;
    c_secret CONSTANT text[] := ARRAY['password_hash', 'admin_word_hash', 'token_hash', 'code_hash'];
BEGIN
    -- maxfiy hash'lar jurnalga yozilmaydi (o'zgargani "update" yozuvining o'zidan ko'rinadi)
    v_old := v_old - c_secret;
    v_new := v_new - c_secret;
    v_key := coalesce(v_new, v_old) ->> 'id';
    IF v_key IS NULL THEN
        v_key := coalesce(coalesce(v_new, v_old) ->> 'line_id', coalesce(v_new, v_old) ->> 'annex_id',
                          coalesce(v_new, v_old) ->> 'user_id');
    END IF;
    INSERT INTO audit_log (user_id, table_name, record_id, action, old_data, new_data)
    VALUES (v_user, TG_TABLE_NAME, coalesce(v_key, '?'), lower(TG_OP), v_old, v_new);
    RETURN NULL;
END $$;

CREATE UNIQUE INDEX app_user_login_lower_key ON app_user (lower(login));

ALTER TABLE project ADD CONSTRAINT project_name_not_blank CHECK (btrim(name) <> '') NOT VALID;
ALTER TABLE quotation_annex ADD CONSTRAINT quotation_annex_name_not_blank CHECK (btrim(name) <> '');
