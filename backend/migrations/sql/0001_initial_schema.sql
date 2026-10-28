-- AVENTOS KP — boshlang'ich sxema (DATABASE_SCHEMA.md 5-versiya, 2026-10-15 tasdiqlangan).
-- Ega: aventos_owner. Dastur (aventos_app) huquqlari default privileges orqali beriladi.
-- Eslatma: psycopg parametrsiz bajaradi, lekin ehtiyot uchun bu faylda foiz belgisi ishlatilmaydi.

-- =====================================================================
-- A. Xodimlar, foydalanuvchilar, rollar, kirish so'rovlari
-- =====================================================================
CREATE TABLE employee (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    legacy_manager_id  integer UNIQUE,
    full_name          text NOT NULL CHECK (btrim(full_name) <> ''),
    phone              text,
    is_active          boolean NOT NULL DEFAULT true
);

CREATE TABLE role (
    code  text PRIMARY KEY,
    name  text NOT NULL
);

CREATE TABLE app_user (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id         bigint NOT NULL UNIQUE REFERENCES employee(id),
    login               text NOT NULL UNIQUE CHECK (btrim(login) <> ''),
    password_hash       text NOT NULL,
    is_active           boolean NOT NULL DEFAULT true,
    access_valid_until  date,
    created_at          timestamptz NOT NULL DEFAULT now(),
    last_login_at       timestamptz
);

CREATE TABLE user_role (
    user_id    bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role_code  text   NOT NULL REFERENCES role(code),
    PRIMARY KEY (user_id, role_code)
);

CREATE TABLE permission (
    code         text PRIMARY KEY,
    name         text NOT NULL,
    description  text
);

CREATE TABLE role_permission (
    role_code        text NOT NULL REFERENCES role(code) ON DELETE CASCADE,
    permission_code  text NOT NULL REFERENCES permission(code),
    PRIMARY KEY (role_code, permission_code)
);

CREATE TABLE user_permission (
    user_id          bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    permission_code  text   NOT NULL REFERENCES permission(code),
    granted_by       bigint NOT NULL REFERENCES app_user(id),
    granted_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, permission_code)
);

CREATE TABLE invitation (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_hash  text NOT NULL UNIQUE,
    created_by  bigint NOT NULL REFERENCES app_user(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    note        text,
    CHECK (expires_at > created_at)
);

CREATE TABLE access_request (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invitation_id    bigint NOT NULL UNIQUE REFERENCES invitation(id),
    full_name        text NOT NULL CHECK (btrim(full_name) <> ''),
    phone            text NOT NULL,
    email            text,
    position         text,
    password_hash    text,
    requested_at     timestamptz NOT NULL DEFAULT now(),
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by      bigint REFERENCES app_user(id),
    reviewed_at      timestamptz,
    review_note      text,
    created_user_id  bigint UNIQUE REFERENCES app_user(id),
    CHECK ((status = 'pending') = (reviewed_by IS NULL AND reviewed_at IS NULL)),
    CHECK ((status = 'approved') = (created_user_id IS NOT NULL)),
    -- parol faqat ko'rib chiqilguncha saqlanadi (keyin app_user da)
    CHECK (status = 'pending' OR password_hash IS NULL)
);

-- =====================================================================
-- B. Ma'lumotnomalar
-- =====================================================================
CREATE TABLE currency (
    code  char(3) PRIMARY KEY CHECK (code = upper(code))
);

CREATE TABLE unit (
    code  text PRIMARY KEY,
    kind  text NOT NULL CHECK (kind IN ('quantity', 'performance'))
);

CREATE TABLE product_category (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    legacy_id  integer UNIQUE,
    name       text NOT NULL UNIQUE
);

CREATE TABLE application_type (
    id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name  text NOT NULL UNIQUE
);

CREATE TABLE brand (
    id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name  text NOT NULL UNIQUE
);

CREATE TABLE product_series (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brand_id  bigint NOT NULL REFERENCES brand(id),
    name      text NOT NULL,
    UNIQUE (brand_id, name)
);

CREATE TABLE project (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_no  integer NOT NULL UNIQUE,
    name        text NOT NULL
);

-- =====================================================================
-- C. Manbalar, narxlar, kurs, QQS
-- =====================================================================
CREATE TABLE source_document (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_name    text NOT NULL,
    sheet_name   text NOT NULL DEFAULT '',
    sha256       char(64) NOT NULL CHECK (sha256 ~ '^[0-9A-F]{64}$'),
    kind         text NOT NULL CHECK (kind IN ('price_list', 'ahu_offer', 'legacy_import')),
    uploaded_by  bigint NOT NULL REFERENCES app_user(id),
    uploaded_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sha256, sheet_name)
);

CREATE TABLE product (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model      text NOT NULL UNIQUE CHECK (btrim(model) <> ''),
    series_id  bigint NOT NULL REFERENCES product_series(id)
);

CREATE TABLE price_list (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                text NOT NULL,
    valid_from          date NOT NULL,
    source_document_id  bigint NOT NULL REFERENCES source_document(id),
    approved_by         bigint REFERENCES app_user(id),
    approved_at         timestamptz,
    CHECK ((approved_by IS NULL) = (approved_at IS NULL))
);

CREATE TABLE price_list_item (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    price_list_id   bigint NOT NULL REFERENCES price_list(id),
    product_id      bigint NOT NULL REFERENCES product(id),
    category_id     bigint REFERENCES product_category(id),
    description     text,
    capacity        numeric(14,3),
    capacity_unit   text REFERENCES unit(code),
    currency_code   char(3) NOT NULL REFERENCES currency(code),
    price_excl_vat  numeric(14,2) NOT NULL CHECK (price_excl_vat >= 0),
    price_incl_vat  numeric(14,2) NOT NULL CHECK (price_incl_vat >= 0),
    source_row      integer NOT NULL CHECK (source_row > 0),
    UNIQUE (price_list_id, product_id)
);

CREATE TABLE vat_rate (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rate         numeric(6,4) NOT NULL CHECK (rate >= 0 AND rate < 1),
    valid_from   date NOT NULL UNIQUE,
    source       text NOT NULL,
    approved_by  bigint NOT NULL REFERENCES app_user(id),
    approved_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE exchange_rate (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_currency  char(3) NOT NULL REFERENCES currency(code),
    to_currency    char(3) NOT NULL REFERENCES currency(code),
    rate           numeric(14,4) NOT NULL CHECK (rate > 0),
    rate_date      date NOT NULL,
    source         text NOT NULL,
    approved_by    bigint NOT NULL REFERENCES app_user(id),
    approved_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (from_currency <> to_currency),
    UNIQUE (from_currency, to_currency, rate_date, source)
);

-- =====================================================================
-- D. AHU fayl importi
-- =====================================================================
CREATE TABLE ahu_block (
    code         text PRIMARY KEY CHECK (code IN ('AHU', 'AUTOMATION', 'VALVE', 'KIT', 'VRF')),
    category_id  bigint NOT NULL REFERENCES product_category(id)
);

CREATE TABLE ahu_offer (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_document_id  bigint NOT NULL UNIQUE REFERENCES source_document(id),
    project_name_raw    text,
    offer_date          date,
    currency_code       char(3) NOT NULL REFERENCES currency(code),
    project_id          bigint REFERENCES project(id)
);

CREATE TABLE ahu_offer_item (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ahu_offer_id    bigint NOT NULL REFERENCES ahu_offer(id),
    source_row      integer NOT NULL CHECK (source_row > 0),
    block_code      text NOT NULL REFERENCES ahu_block(code),
    parent_item_id  bigint REFERENCES ahu_offer_item(id),
    model           text,
    air_flow        numeric(14,3),
    flow_kg_h       numeric(14,6),
    description     text,
    quantity        numeric(14,3) NOT NULL CHECK (quantity > 0),
    unit_price      numeric(14,2) NOT NULL CHECK (unit_price >= 0),
    is_hidden_row   boolean NOT NULL DEFAULT false,
    UNIQUE (ahu_offer_id, source_row),
    CHECK (parent_item_id IS NULL OR parent_item_id <> id),
    -- AHU qatori ota qatorsiz; automation/valve/kit ota AHU ga bog'lanadi
    CHECK ((block_code = 'AHU') = (parent_item_id IS NULL) OR block_code = 'VRF')
);

CREATE TABLE ahu_offer_item_tag (
    item_id  bigint NOT NULL REFERENCES ahu_offer_item(id),
    tag      text   NOT NULL CHECK (btrim(tag) <> ''),
    PRIMARY KEY (item_id, tag)
);

-- =====================================================================
-- E. KP
-- =====================================================================
CREATE TABLE quotation (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kp_number   bigint NOT NULL UNIQUE CHECK (kp_number > 0),
    project_id  bigint NOT NULL REFERENCES project(id),
    manager_id  bigint NOT NULL REFERENCES employee(id),
    created_by  bigint NOT NULL REFERENCES app_user(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quotation_revision (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quotation_id        bigint NOT NULL REFERENCES quotation(id),
    revision_no         integer NOT NULL CHECK (revision_no > 0),
    kp_date             date NOT NULL,
    validity_days       integer NOT NULL DEFAULT 14 CHECK (validity_days > 0),
    display_currency    char(3) NOT NULL REFERENCES currency(code),
    exchange_rate_id    bigint REFERENCES exchange_rate(id),
    vat_rate_id         bigint NOT NULL REFERENCES vat_rate(id),
    show_excl_vat_note  boolean NOT NULL DEFAULT false,
    status              text NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'approved', 'sent', 'cancelled')),
    approved_by         bigint REFERENCES app_user(id),
    approved_at         timestamptz,
    UNIQUE (quotation_id, revision_no),
    CHECK (display_currency <> 'UZS' OR exchange_rate_id IS NOT NULL),
    CHECK ((approved_by IS NULL) = (approved_at IS NULL)),
    CHECK (status NOT IN ('approved', 'sent') OR approved_by IS NOT NULL)
);

CREATE TABLE quotation_annex (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    revision_id          bigint NOT NULL REFERENCES quotation_revision(id),
    annex_no             integer NOT NULL CHECK (annex_no BETWEEN 1 AND 12),
    name                 text NOT NULL,
    application_type_id  bigint REFERENCES application_type(id),
    UNIQUE (revision_id, annex_no)
);

CREATE TABLE quotation_line (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    annex_id    bigint NOT NULL REFERENCES quotation_annex(id),
    line_no     integer NOT NULL CHECK (line_no > 0),
    line_type   text NOT NULL CHECK (line_type IN ('price_list', 'ahu', 'custom')),
    quantity    numeric(14,3) NOT NULL CHECK (quantity > 0),
    unit_code   text NOT NULL REFERENCES unit(code),
    margin_pct  numeric(6,4) CHECK (margin_pct >= 0 AND margin_pct < 1),
    UNIQUE (annex_id, line_no),
    -- narx ro'yxati modellariga marja qo'shilmaydi (CLAUDE.md)
    CHECK (line_type <> 'price_list' OR margin_pct IS NULL)
);

CREATE TABLE quotation_line_price_list (
    line_id             bigint PRIMARY KEY REFERENCES quotation_line(id) ON DELETE CASCADE,
    price_list_item_id  bigint NOT NULL REFERENCES price_list_item(id)
);

CREATE TABLE quotation_line_ahu_item (
    line_id            bigint NOT NULL REFERENCES quotation_line(id) ON DELETE CASCADE,
    ahu_offer_item_id  bigint NOT NULL REFERENCES ahu_offer_item(id),
    include_in_price   boolean NOT NULL DEFAULT true,
    PRIMARY KEY (line_id, ahu_offer_item_id)
);

CREATE TABLE quotation_line_custom (
    line_id                  bigint PRIMARY KEY REFERENCES quotation_line(id) ON DELETE CASCADE,
    category_id              bigint REFERENCES product_category(id),
    model                    text,
    description              text NOT NULL,
    performance              numeric(14,3),
    performance_unit         text REFERENCES unit(code),
    unit_price_excl_vat      numeric(14,2) NOT NULL CHECK (unit_price_excl_vat >= 0),
    price_incl_vat_override  numeric(14,2) CHECK (price_incl_vat_override >= 0),
    currency_code            char(3) NOT NULL REFERENCES currency(code)
);

-- =====================================================================
-- F. Chegirma (har bir ilovaga, foizda, QQS bilan summadan)
-- =====================================================================
CREATE TABLE annex_discount (
    annex_id      bigint PRIMARY KEY REFERENCES quotation_annex(id) ON DELETE CASCADE,
    discount_pct  numeric(6,4) NOT NULL CHECK (discount_pct > 0 AND discount_pct < 1),
    reason        text,
    created_by    bigint NOT NULL REFERENCES app_user(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================
-- G. Nazorat
-- =====================================================================
CREATE TABLE audit_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint REFERENCES app_user(id),
    table_name  text NOT NULL,
    record_id   text NOT NULL,
    action      text NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
    old_data    jsonb,
    new_data    jsonb,
    at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE data_issue (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name   text NOT NULL,
    record_id    text NOT NULL,
    issue_code   text NOT NULL,
    details      text,
    found_at     timestamptz NOT NULL DEFAULT now(),
    resolved_by  bigint REFERENCES app_user(id),
    resolved_at  timestamptz,
    resolution   text,
    CHECK ((resolved_by IS NULL) = (resolved_at IS NULL)),
    CHECK (resolved_by IS NULL OR resolution IS NOT NULL)
);

-- Tez-tez qidiriladigan tashqi kalitlar uchun indekslar
CREATE INDEX ix_price_list_item_product ON price_list_item(product_id);
CREATE INDEX ix_ahu_offer_item_offer    ON ahu_offer_item(ahu_offer_id);
CREATE INDEX ix_ahu_offer_item_parent   ON ahu_offer_item(parent_item_id);
CREATE INDEX ix_quotation_project       ON quotation(project_id);
CREATE INDEX ix_quotation_manager       ON quotation(manager_id);
CREATE INDEX ix_revision_quotation      ON quotation_revision(quotation_id);
CREATE INDEX ix_annex_revision          ON quotation_annex(revision_id);
CREATE INDEX ix_line_annex              ON quotation_line(annex_id);
CREATE INDEX ix_line_ahu_item_item      ON quotation_line_ahu_item(ahu_offer_item_id);
CREATE INDEX ix_line_price_list_item    ON quotation_line_price_list(price_list_item_id);
CREATE INDEX ix_audit_table_record      ON audit_log(table_name, record_id);
CREATE INDEX ix_data_issue_open         ON data_issue(table_name, record_id) WHERE resolved_at IS NULL;

-- =====================================================================
-- Himoya triggerlari
-- =====================================================================

-- 1) Faqat qo'shiladigan jadvallar: o'zgartirish va o'chirish taqiqlanadi
CREATE FUNCTION trg_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = TG_TABLE_NAME || ' jadvali faqat qo''shiladi: ' || TG_OP || ' taqiqlangan',
        ERRCODE = 'P0001';
END $$;

CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON source_document    FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON vat_rate           FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON exchange_rate      FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON ahu_offer_item     FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON ahu_offer_item_tag FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON audit_log          FOR EACH ROW EXECUTE FUNCTION trg_append_only();

-- 2) Tasdiqlangan narx ro'yxati o'zgarmaydi
CREATE FUNCTION trg_price_list_item_lock() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_list_id bigint := CASE WHEN TG_OP = 'DELETE' THEN OLD.price_list_id ELSE NEW.price_list_id END;
BEGIN
    IF TG_OP <> 'INSERT' AND OLD.price_list_id <> v_list_id THEN
        v_list_id := OLD.price_list_id;
    END IF;
    IF EXISTS (SELECT 1 FROM price_list WHERE id = v_list_id AND approved_at IS NOT NULL)
       OR (TG_OP <> 'INSERT' AND EXISTS (SELECT 1 FROM price_list WHERE id = OLD.price_list_id AND approved_at IS NOT NULL)) THEN
        RAISE EXCEPTION USING MESSAGE = 'Tasdiqlangan narx ro''yxatini o''zgartirib bo''lmaydi (yangi versiya yarating)', ERRCODE = 'P0001';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON price_list_item
    FOR EACH ROW EXECUTE FUNCTION trg_price_list_item_lock();

CREATE FUNCTION trg_price_list_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.approved_at IS NOT NULL THEN
        RAISE EXCEPTION USING MESSAGE = 'Tasdiqlangan narx ro''yxatini o''zgartirib bo''lmaydi', ERRCODE = 'P0001';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER lock_approved BEFORE UPDATE OR DELETE ON price_list
    FOR EACH ROW EXECUTE FUNCTION trg_price_list_lock();

-- 3) Tasdiqlangan/yuborilgan KP revisioni tahrirlanmaydi
CREATE FUNCTION revision_is_locked(p_revision_id bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM quotation_revision
                   WHERE id = p_revision_id AND status IN ('approved', 'sent', 'cancelled'));
$$;

CREATE FUNCTION trg_revision_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION USING MESSAGE = 'Faqat qoralama (draft) revisionni o''chirish mumkin', ERRCODE = 'P0001';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'draft' THEN
        RETURN NEW;
    END IF;
    -- Qulflangan revisionda faqat holat o'tishi mumkin: approved -> sent / cancelled, sent -> cancelled
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
CREATE TRIGGER lock_approved BEFORE UPDATE OR DELETE ON quotation_revision
    FOR EACH ROW EXECUTE FUNCTION trg_revision_lock();

CREATE FUNCTION revision_of_annex(p_annex_id bigint) RETURNS bigint
LANGUAGE sql STABLE AS $$ SELECT revision_id FROM quotation_annex WHERE id = p_annex_id; $$;

CREATE FUNCTION revision_of_line(p_line_id bigint) RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT a.revision_id FROM quotation_line l JOIN quotation_annex a ON a.id = l.annex_id WHERE l.id = p_line_id;
$$;


CREATE FUNCTION assert_revision_editable(p_revision_id bigint) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF p_revision_id IS NOT NULL AND revision_is_locked(p_revision_id) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'KP revisioni tasdiqlangan/yuborilgan — tahrirlab bo''lmaydi (yangi revision yarating)',
            ERRCODE = 'P0001';
    END IF;
END $$;

CREATE FUNCTION trg_annex_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM assert_revision_editable(OLD.revision_id); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM assert_revision_editable(NEW.revision_id); END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON quotation_annex
    FOR EACH ROW EXECUTE FUNCTION trg_annex_lock();

CREATE FUNCTION trg_by_annex_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM assert_revision_editable(revision_of_annex(OLD.annex_id)); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM assert_revision_editable(revision_of_annex(NEW.annex_id)); END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON quotation_line
    FOR EACH ROW EXECUTE FUNCTION trg_by_annex_lock();
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON annex_discount
    FOR EACH ROW EXECUTE FUNCTION trg_by_annex_lock();

CREATE FUNCTION trg_by_line_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM assert_revision_editable(revision_of_line(OLD.line_id)); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM assert_revision_editable(revision_of_line(NEW.line_id)); END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON quotation_line_price_list
    FOR EACH ROW EXECUTE FUNCTION trg_by_line_lock();
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON quotation_line_ahu_item
    FOR EACH ROW EXECUTE FUNCTION trg_by_line_lock();
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON quotation_line_custom
    FOR EACH ROW EXECUTE FUNCTION trg_by_line_lock();

-- 4) Qator turi va tafsilot jadvali mos bo'lishi shart
CREATE FUNCTION trg_line_subtype_match() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_type text;
    v_expected text := CASE TG_TABLE_NAME
        WHEN 'quotation_line_price_list' THEN 'price_list'
        WHEN 'quotation_line_ahu_item'   THEN 'ahu'
        WHEN 'quotation_line_custom'     THEN 'custom' END;
BEGIN
    SELECT line_type INTO v_type FROM quotation_line WHERE id = NEW.line_id;
    IF v_type IS DISTINCT FROM v_expected THEN
        RAISE EXCEPTION USING
            MESSAGE = TG_TABLE_NAME || ' faqat ' || v_expected || ' turidagi qator uchun (qator turi: ' || coalesce(v_type, '?') || ')',
            ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER subtype_match BEFORE INSERT OR UPDATE ON quotation_line_price_list FOR EACH ROW EXECUTE FUNCTION trg_line_subtype_match();
CREATE TRIGGER subtype_match BEFORE INSERT OR UPDATE ON quotation_line_ahu_item   FOR EACH ROW EXECUTE FUNCTION trg_line_subtype_match();
CREATE TRIGGER subtype_match BEFORE INSERT OR UPDATE ON quotation_line_custom     FOR EACH ROW EXECUTE FUNCTION trg_line_subtype_match();

-- Tranzaksiya oxirida: har bir qatorda tafsilot bor (ahu da narxga kiruvchi kamida bitta band)
CREATE FUNCTION trg_line_has_detail() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_line quotation_line;
    v_ok boolean;
BEGIN
    SELECT * INTO v_line FROM quotation_line WHERE id = NEW.id;
    IF NOT FOUND THEN RETURN NULL; END IF;   -- shu tranzaksiyada o'chirilgan
    v_ok := CASE v_line.line_type
        WHEN 'price_list' THEN EXISTS (SELECT 1 FROM quotation_line_price_list WHERE line_id = v_line.id)
        WHEN 'custom'     THEN EXISTS (SELECT 1 FROM quotation_line_custom WHERE line_id = v_line.id)
        WHEN 'ahu'        THEN EXISTS (SELECT 1 FROM quotation_line_ahu_item WHERE line_id = v_line.id AND include_in_price)
    END;
    IF NOT v_ok THEN
        RAISE EXCEPTION USING
            MESSAGE = 'KP qatori ' || v_line.id || ' (' || v_line.line_type || ') uchun tafsilot yozuvi yo''q',
            ERRCODE = 'P0001';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER line_has_detail AFTER INSERT OR UPDATE ON quotation_line
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_line_has_detail();

-- 5) Chegirmani faqat admin beradi
CREATE FUNCTION user_has_role(p_user_id bigint, p_role text) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM user_role WHERE user_id = p_user_id AND role_code = p_role);
$$;

CREATE FUNCTION trg_discount_admin_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT user_has_role(NEW.created_by, 'admin') THEN
        RAISE EXCEPTION USING MESSAGE = 'Chegirmani faqat admin bera oladi', ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER admin_only BEFORE INSERT OR UPDATE ON annex_discount
    FOR EACH ROW EXECUTE FUNCTION trg_discount_admin_only();

-- 6) Audit jurnali. Dastur har tranzaksiyada: SET LOCAL app.user_id = '<id>'
CREATE FUNCTION trg_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_user bigint := nullif(current_setting('app.user_id', true), '')::bigint;
    v_old jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
    v_new jsonb := CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN to_jsonb(NEW) END;
    v_key text;
BEGIN
    -- parol hash'lari jurnalga yozilmaydi
    v_old := v_old - 'password_hash';
    v_new := v_new - 'password_hash';
    v_key := coalesce(v_new, v_old) ->> 'id';
    IF v_key IS NULL THEN
        v_key := coalesce(coalesce(v_new, v_old) ->> 'line_id', coalesce(v_new, v_old) ->> 'annex_id',
                          coalesce(v_new, v_old) ->> 'user_id');
    END IF;
    INSERT INTO audit_log (user_id, table_name, record_id, action, old_data, new_data)
    VALUES (v_user, TG_TABLE_NAME, coalesce(v_key, '?'), lower(TG_OP), v_old, v_new);
    RETURN NULL;
END $$;

CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON price_list            FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON vat_rate              FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON exchange_rate         FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation             FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation_revision    FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation_line        FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation_line_custom FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON annex_discount        FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON app_user              FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON user_role             FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON user_permission       FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON access_request        FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON data_issue            FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- =====================================================================
-- Hisoblash ko'rinishlari (view) — summalar saqlanmaydi
-- =====================================================================

-- Har bir qator: model, tavsif, quvvat, narxlar (CLAUDE.md qoidalari)
CREATE VIEW v_line_price AS
WITH ahu_sum AS (
    SELECT li.line_id, sum(i.unit_price) AS base_price
    FROM quotation_line_ahu_item li
    JOIN ahu_offer_item i ON i.id = li.ahu_offer_item_id
    WHERE li.include_in_price
    GROUP BY li.line_id
),
ahu_main AS (   -- qatorning asosiy bandi: AHU (ota) yoki valve/boshqa yagona narx bandi
    SELECT DISTINCT ON (li.line_id) li.line_id, i.*
    FROM quotation_line_ahu_item li
    JOIN ahu_offer_item i ON i.id = li.ahu_offer_item_id
    WHERE li.include_in_price
    ORDER BY li.line_id, (i.block_code = 'AHU') DESC, (i.block_code = 'VALVE') DESC, i.source_row
),
ahu_automation AS (
    SELECT li.line_id, string_agg(i.description, ' ' ORDER BY i.source_row) AS text
    FROM quotation_line_ahu_item li
    JOIN ahu_offer_item i ON i.id = li.ahu_offer_item_id
    WHERE li.include_in_price AND i.block_code = 'AUTOMATION'
    GROUP BY li.line_id
),
ahu_valves_text AS (   -- "faqat AHU + valve" KP: valve'lar AHU tavsifida (narxsiz)
    SELECT li.line_id,
           string_agg(i.model || ' ' || coalesce(i.description, ''), E'\n' ORDER BY i.source_row) AS text
    FROM quotation_line_ahu_item li
    JOIN ahu_offer_item i ON i.id = li.ahu_offer_item_id
    WHERE NOT li.include_in_price AND i.block_code = 'VALVE'
    GROUP BY li.line_id
),
base AS (
    SELECT
        l.id AS line_id, l.annex_id, l.line_no, l.line_type, l.quantity, l.unit_code, l.margin_pct,
        a.revision_id,
        CASE l.line_type
            WHEN 'price_list' THEN pli.price_excl_vat
            WHEN 'ahu'        THEN s.base_price
            WHEN 'custom'     THEN c.unit_price_excl_vat
        END AS base_price,
        CASE l.line_type
            WHEN 'price_list' THEN pli.price_incl_vat
            WHEN 'custom'     THEN c.price_incl_vat_override
        END AS fixed_price_incl_vat,
        CASE l.line_type
            WHEN 'price_list' THEN pli.currency_code
            WHEN 'ahu'        THEN o.currency_code
            WHEN 'custom'     THEN c.currency_code
        END AS price_currency,
        CASE l.line_type
            WHEN 'price_list' THEN pr.model
            WHEN 'custom'     THEN c.model
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE'
                                 THEN left(m.model, 4) || ' ' || left(coalesce(m.description, ''), 6)
                                 ELSE m.model END
        END AS model,
        CASE l.line_type
            WHEN 'price_list' THEN pli.description
            WHEN 'custom'     THEN c.description
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE'
                                 THEN m.model || ' ' || coalesce(m.description, '')
                                 ELSE concat_ws(' ', m.model, au.text)
                                      || coalesce(E'\n\n\n' || vt.text, '') END
        END AS description,
        CASE l.line_type
            WHEN 'price_list' THEN pli.capacity
            WHEN 'custom'     THEN c.performance
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE' THEN m.flow_kg_h ELSE m.air_flow END
        END AS performance,
        CASE l.line_type
            WHEN 'price_list' THEN pli.capacity_unit
            WHEN 'custom'     THEN c.performance_unit
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE' THEN 'kg/h' ELSE 'm3/h' END
        END AS performance_unit,
        CASE l.line_type
            WHEN 'price_list' THEN pli.category_id
            WHEN 'custom'     THEN c.category_id
            WHEN 'ahu'        THEN b.category_id
        END AS category_id
    FROM quotation_line l
    JOIN quotation_annex a ON a.id = l.annex_id
    LEFT JOIN quotation_line_price_list lp ON lp.line_id = l.id
    LEFT JOIN price_list_item pli ON pli.id = lp.price_list_item_id
    LEFT JOIN product pr ON pr.id = pli.product_id
    LEFT JOIN quotation_line_custom c ON c.line_id = l.id
    LEFT JOIN ahu_sum s ON s.line_id = l.id
    LEFT JOIN ahu_main m ON m.line_id = l.id
    LEFT JOIN ahu_offer o ON o.id = m.ahu_offer_id
    LEFT JOIN ahu_block b ON b.code = m.block_code
    LEFT JOIN ahu_automation au ON au.line_id = l.id
    LEFT JOIN ahu_valves_text vt ON vt.line_id = l.id
),
priced AS (
    SELECT b.*,
           -- Marjali narx: ROUNDUP(bazaviy / (1 - marja), 0)
           CASE WHEN b.margin_pct IS NULL THEN b.base_price
                ELSE ceil(b.base_price / (1 - b.margin_pct)) END AS unit_price_excl_vat,
           r.display_currency, er.rate AS exchange_rate, vr.rate AS vat_rate
    FROM base b
    JOIN quotation_revision r ON r.id = b.revision_id
    JOIN vat_rate vr ON vr.id = r.vat_rate_id
    LEFT JOIN exchange_rate er ON er.id = r.exchange_rate_id
)
SELECT p.*,
       -- QQS bilan narx: ROUNDUP(marjali × (1 + QQS), 0) yoki manbadagi qat'iy qiymat.
       -- Valyuta: bir xil bo'lsa ×1, USD→UZS bo'lsa ×kurs, boshqa yo'nalish NULL (xato yashirinmaydi).
       coalesce(p.fixed_price_incl_vat, ceil(p.unit_price_excl_vat * (1 + p.vat_rate))) AS unit_price_incl_vat,
       coalesce(p.fixed_price_incl_vat, ceil(p.unit_price_excl_vat * (1 + p.vat_rate)))
         * CASE WHEN p.display_currency = p.price_currency THEN 1
              WHEN p.price_currency = 'USD' AND p.display_currency = 'UZS' THEN p.exchange_rate END AS display_unit_price,
       coalesce(p.fixed_price_incl_vat, ceil(p.unit_price_excl_vat * (1 + p.vat_rate)))
         * CASE WHEN p.display_currency = p.price_currency THEN 1
              WHEN p.price_currency = 'USD' AND p.display_currency = 'UZS' THEN p.exchange_rate END
         * p.quantity AS display_line_total
FROM priced p;

-- Ilova jamlari va chegirma (QQS bilan, KP valyutasida, yaxlitlanmaydi)
CREATE VIEW v_annex_totals AS
SELECT a.id AS annex_id, a.revision_id, a.annex_no, a.name,
       coalesce(sum(lp.display_line_total), 0) AS subtotal,
       coalesce(sum(lp.quantity), 0) AS total_quantity,
       d.discount_pct,
       coalesce(sum(lp.display_line_total), 0) * coalesce(d.discount_pct, 0) AS discount_amount,
       coalesce(sum(lp.display_line_total), 0) * (1 - coalesce(d.discount_pct, 0)) AS total_after_discount,
       d.reason AS discount_reason, d.created_by AS discount_by, d.created_at AS discount_at
FROM quotation_annex a
LEFT JOIN v_line_price lp ON lp.annex_id = a.id
LEFT JOIN annex_discount d ON d.annex_id = a.id
GROUP BY a.id, a.revision_id, a.annex_no, a.name, d.discount_pct, d.reason, d.created_by, d.created_at;

-- KP (revision) jamlari
CREATE VIEW v_quotation_totals AS
SELECT r.id AS revision_id, q.kp_number, r.revision_no, r.status, r.kp_date,
       r.kp_date + r.validity_days AS valid_until,
       r.display_currency,
       count(t.annex_id) AS annex_count,
       coalesce(sum(t.subtotal), 0) AS subtotal,
       coalesce(sum(t.discount_amount), 0) AS discount_amount,
       coalesce(sum(t.total_after_discount), 0) AS total_incl_vat,
       -- faqat ma'lumot uchun (pastda): QQSsiz va QQS summasi
       coalesce(sum(t.total_after_discount), 0) / (1 + vr.rate) AS total_excl_vat_info,
       coalesce(sum(t.total_after_discount), 0) - coalesce(sum(t.total_after_discount), 0) / (1 + vr.rate) AS vat_amount_info,
       r.show_excl_vat_note
FROM quotation_revision r
JOIN quotation q ON q.id = r.quotation_id
JOIN vat_rate vr ON vr.id = r.vat_rate_id
LEFT JOIN v_annex_totals t ON t.revision_id = r.id
GROUP BY r.id, q.kp_number, r.revision_no, r.status, r.kp_date, r.validity_days, r.display_currency, vr.rate, r.show_excl_vat_note;

-- Loyiha bo'yicha chegirma hisoboti: har KP ning oxirgi tasdiqlangan/yuborilgan revisioni, har ilova alohida
CREATE VIEW v_project_discounts AS
WITH latest AS (
    SELECT DISTINCT ON (r.quotation_id) r.*
    FROM quotation_revision r
    WHERE r.status IN ('approved', 'sent')
    ORDER BY r.quotation_id, r.revision_no DESC
)
SELECT p.project_no, p.name AS project_name,
       q.kp_number, l.revision_no, l.kp_date,
       e.id AS manager_id, e.full_name AS manager_name,
       l.display_currency,
       t.annex_no, t.name AS annex_name,
       t.subtotal, t.discount_pct, t.discount_amount, t.total_after_discount,
       de.full_name AS discount_by_name, t.discount_at, t.discount_reason
FROM latest l
JOIN quotation q ON q.id = l.quotation_id
JOIN project p ON p.id = q.project_id
JOIN employee e ON e.id = q.manager_id
JOIN v_annex_totals t ON t.revision_id = l.id
LEFT JOIN app_user du ON du.id = t.discount_by
LEFT JOIN employee de ON de.id = du.employee_id;

-- Narx ro'yxati: QQS bilan narx qoidaga (ROUNDUP(QQSsiz × (1+QQS), 0)) mos kelmaydiganlar
CREATE VIEW v_price_list_check AS
SELECT pli.id AS price_list_item_id, pl.name AS price_list, pr.model,
       pli.price_excl_vat, pli.price_incl_vat,
       vr.rate AS vat_rate,
       ceil(pli.price_excl_vat * (1 + vr.rate)) AS expected_incl_vat,
       CASE WHEN vr.rate IS NULL THEN 'TEKSHIRISH KERAK (QQS stavkasi yo''q)'
            WHEN pli.price_incl_vat = ceil(pli.price_excl_vat * (1 + vr.rate)) THEN 'OK'
            ELSE 'TEKSHIRISH KERAK' END AS check_status
FROM price_list_item pli
JOIN price_list pl ON pl.id = pli.price_list_id
JOIN product pr ON pr.id = pli.product_id
LEFT JOIN LATERAL (
    SELECT rate FROM vat_rate WHERE valid_from <= pl.valid_from ORDER BY valid_from DESC LIMIT 1
) vr ON true;

-- Foydalanuvchining amaldagi ruxsatlari = rollar ruxsatlari ∪ alohida berilganlar
CREATE VIEW v_user_effective_permission AS
SELECT ur.user_id, rp.permission_code, 'role:' || ur.role_code AS granted_via
FROM user_role ur JOIN role_permission rp ON rp.role_code = ur.role_code
UNION
SELECT up.user_id, up.permission_code, 'user' AS granted_via
FROM user_permission up;

-- Hozir tizimga kira oladigan foydalanuvchilar (faol va muddati o'tmagan)
CREATE VIEW v_active_user AS
SELECT u.id AS user_id, u.login, e.full_name, u.access_valid_until
FROM app_user u JOIN employee e ON e.id = u.employee_id
WHERE u.is_active AND e.is_active
  AND (u.access_valid_until IS NULL OR u.access_valid_until >= current_date);

-- =====================================================================
-- Boshlang'ich ma'lumotnomalar
-- =====================================================================
INSERT INTO role (code, name) VALUES
    ('admin',   'Administrator'),
    ('manager', 'Menejer (faqat o''z KP larini ko''radi)');

INSERT INTO permission (code, name) VALUES
    ('kp.view_own',          'O''zi menejer bo''lgan KP larni ko''rish'),
    ('kp.view_all',          'Barcha KP larni ko''rish'),
    ('kp.download',          'KP ni Excel/PDF qilib yuklab olish'),
    ('kp.create_edit',       'KP yaratish va tahrirlash (qoralama)'),
    ('kp.approve',           'KP ni tasdiqlash / yuborilgan deb belgilash'),
    ('discount.manage',      'Ilovaga chegirma berish'),
    ('discount.report_own',  'O''z loyihalari bo''yicha chegirma hisoboti'),
    ('discount.report_all',  'Barcha loyihalar bo''yicha chegirma hisoboti'),
    ('price.view',           'Narx ro''yxatini ko''rish'),
    ('price.manage',         'Narx ro''yxati, marja, kurs, QQS ni kiritish'),
    ('ahu.import',           'AHU faylini yuklash'),
    ('project.manage',       'Loyihalarni qo''shish/tahrirlash'),
    ('data_issue.resolve',   '"TEKSHIRISH KERAK" yozuvlarini hal qilish'),
    ('user.manage',          'So''rovlarni tasdiqlash, muddat va ruxsatlarni belgilash');

INSERT INTO role_permission (role_code, permission_code)
SELECT 'admin', code FROM permission;
INSERT INTO role_permission (role_code, permission_code) VALUES
    ('manager', 'kp.view_own'),
    ('manager', 'kp.download'),
    ('manager', 'discount.report_own');

INSERT INTO currency (code) VALUES ('USD'), ('UZS');

INSERT INTO unit (code, kind) VALUES
    ('шт', 'quantity'), ('м', 'quantity'), ('кг', 'quantity'), ('м2', 'quantity'),
    ('система', 'quantity'), ('комп', 'quantity'),
    ('kw', 'performance'), ('m3/h', 'performance'), ('kg/h', 'performance'),
    ('btu', 'performance'), ('л', 'performance');

-- Dastur audit jurnalini o'zgartira olmaydi (faqat qo'shadi)
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM aventos_app;
REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM aventos_app;
