-- 0025 (2026-10-22): MAHSULOT (QATOR) CHEGIRMASI va CHEGIRMA ISBOTI (skrinshot). Foydalanuvchi qarorlari 2026-10-22:
--   - chegirma har qatorga: foizda yoki summada (1 dona uchun, KP valyutasida), QQS bilan narxdan; chegirmali narx ROUNDUP(…, 0);
--   - faqat admin beradi (bazada tekshiriladi); sabab matni majburiy, isbot (skrinshot/PDF) ixtiyoriy;
--   - tartib: avval mahsulot chegirmasi, keyin ilova chegirmasi (ilova foizi mahsulot chegirmalaridan keyingi summadan);
--   - isbot ilova chegirmasiga ham biriktiriladi; isbot fayli o'chirilmaydi (faqat qo'shiladi, KP butunlay o'chirilganda birga).
-- Mavjud KP lar: chegirma yozuvi yo'q — barcha summalar AYNAN avvalgidek (v_annex_totals.subtotal = brutto, ilova chegirmasi netto dan).

CREATE TABLE line_discount (
    line_id    bigint PRIMARY KEY REFERENCES quotation_line(id) ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('pct', 'amount')),
    value      numeric NOT NULL CHECK (value > 0 AND (kind <> 'pct' OR value < 1)),
    reason     text NOT NULL CHECK (btrim(reason) <> ''),
    created_by bigint NOT NULL REFERENCES app_user(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE line_discount IS 'Mahsulot (KP qatori) chegirmasi: pct — 0..1 kasr; amount — 1 dona uchun KP valyutasida, QQS bilan narxdan';
CREATE TRIGGER admin_only BEFORE INSERT OR UPDATE ON line_discount FOR EACH ROW EXECUTE FUNCTION trg_discount_admin_only();
CREATE TRIGGER lock_approved BEFORE INSERT OR UPDATE OR DELETE ON line_discount FOR EACH ROW EXECUTE FUNCTION trg_by_line_lock();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON line_discount FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- Isbot fayllari (bazada — zaxiraga ham kiradi). O'zgarmaydi; faqat KP butunlay o'chirilganda birga o'chadi.
CREATE TABLE discount_evidence (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quotation_id bigint NOT NULL REFERENCES quotation(id),
    file_name    text NOT NULL CHECK (btrim(file_name) <> ''),
    content_type text NOT NULL CHECK (content_type IN ('image/png', 'image/jpeg', 'image/webp', 'application/pdf')),
    size_bytes   integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
    sha256       char(64) NOT NULL CHECK (sha256 ~ '^[0-9A-F]{64}$'),
    data         bytea NOT NULL,
    uploaded_by  bigint NOT NULL REFERENCES app_user(id),
    uploaded_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (quotation_id, sha256)
);
COMMENT ON TABLE discount_evidence IS 'Chegirma isboti (skrinshot/PDF) — append-only; audit_log ga yozilmaydi (fayl katta), o''zida kim/qachon bor';
CREATE FUNCTION trg_evidence_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND kp_delete_in_progress() THEN RETURN OLD; END IF;
    RAISE EXCEPTION USING MESSAGE = 'Chegirma isboti o''zgartirilmaydi va o''chirilmaydi: ' || TG_OP || ' taqiqlangan', ERRCODE = 'P0001';
END $$;
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON discount_evidence FOR EACH ROW EXECUTE FUNCTION trg_evidence_append_only();

-- Isbot qaysi chegirmaga (qator yoki ilova) tegishli. Tasdiqlangan KP ga ham keyinroq isbot qo'shish mumkin (narxga ta'siri yo'q).
CREATE TABLE discount_evidence_link (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evidence_id bigint NOT NULL REFERENCES discount_evidence(id),
    line_id     bigint REFERENCES quotation_line(id) ON DELETE CASCADE,
    annex_id    bigint REFERENCES quotation_annex(id) ON DELETE CASCADE,
    created_by  bigint NOT NULL REFERENCES app_user(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK ((line_id IS NULL) <> (annex_id IS NULL)),
    UNIQUE (evidence_id, line_id),
    UNIQUE (evidence_id, annex_id)
);
CREATE INDEX ix_evidence_link_line ON discount_evidence_link (line_id) WHERE line_id IS NOT NULL;
CREATE INDEX ix_evidence_link_annex ON discount_evidence_link (annex_id) WHERE annex_id IS NOT NULL;
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON discount_evidence_link FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- KP ni butunlay o'chirish: isbot fayllari ham (avval qatorlar va ilovalar — bog'lanishlar CASCADE bilan)
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
    DELETE FROM discount_evidence WHERE quotation_id = v_q;
    DELETE FROM quotation WHERE id = v_q;
    PERFORM set_config('app.kp_delete', '', true);
    RETURN v_revisions;
END $$;

DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price;

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
ahu_lines AS (      -- KP dagi AHU qatorlari va keyingi AHU qatorigacha bo'lgan guruh chegarasi
    SELECT am.line_id, l.annex_id, l.line_no, am.id AS ahu_item_id,
           lead(l.line_no) OVER (PARTITION BY l.annex_id ORDER BY l.line_no) AS next_no
    FROM ahu_main am JOIN quotation_line l ON l.id = am.line_id
    WHERE am.block_code = 'AHU'
),
ahu_kkb AS (        -- 2026-10-16: AHU guruhida (KP qatorlarida) shu AHU ning VRF (ККБ) / AHU kit modeli bormi
    SELECT al.line_id, bool_or(ch.block_code = 'VRF') AS has_vrf, bool_or(ch.block_code = 'KIT') AS has_kit
    FROM ahu_lines al
    JOIN quotation_line g ON g.annex_id = al.annex_id AND g.line_no > al.line_no
                         AND (al.next_no IS NULL OR g.line_no < al.next_no) AND g.line_type = 'price_list'
    JOIN quotation_line_price_list gp ON gp.line_id = g.id
    JOIN price_list_item gi ON gi.id = gp.price_list_item_id
    JOIN product gpr ON gpr.id = gi.product_id
    JOIN ahu_offer_item ch ON ch.parent_item_id = al.ahu_item_id AND ch.block_code IN ('VRF', 'KIT')
                          AND NOT ch.is_hidden_row AND ch.model = gpr.model
    GROUP BY al.line_id
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
            -- CLAUDE.md: AHU qatori K = AHU fayldagi "AHU" ustuni (A) matni; valve K = CONCAT(LEFT(C,4)," ",LEFT(D,6))
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE'
                                 THEN left(m.model, 4) || ' ' || left(coalesce(m.description, ''), 6)
                                 ELSE m.unit_label END
        END AS model,
        CASE l.line_type
            WHEN 'price_list' THEN pli.description
            WHEN 'custom'     THEN c.description
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE'
                                 THEN m.model || ' ' || coalesce(m.description, '')
                                 ELSE concat_ws(' ', m.model, au.text)
                                      || coalesce(CASE WHEN rr.approved_at < TIMESTAMPTZ '2026-10-16 16:30:00+05' THEN E'\n\n\n' ELSE E'\n\n' END || vt.text, '')
                                      -- KP da VRF qatori bo'lsa: 1 bo'sh qator + "с ККБ и AHU kit"; faqat AHU kit bo'lsa: "с AHU kit"
                                      || CASE WHEN k.has_vrf THEN E'\n\nс ККБ и AHU kit' WHEN k.has_kit THEN E'\n\nс AHU kit' ELSE '' END END
        END AS description,
        CASE l.line_type
            WHEN 'price_list' THEN pli.capacity
            WHEN 'custom'     THEN c.performance
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE' THEN round(m.flow_kg_h) ELSE m.air_flow END
        END AS performance,
        CASE l.line_type
            WHEN 'price_list' THEN pli.capacity_unit
            WHEN 'custom'     THEN c.performance_unit
            WHEN 'ahu' THEN CASE WHEN m.block_code = 'VALVE' THEN 'kg/h' ELSE 'm3/h' END
        END AS performance_unit,
        CASE l.line_type
            WHEN 'price_list' THEN coalesce(lp.category_id, pli.category_id)
            WHEN 'custom'     THEN c.category_id
            WHEN 'ahu'        THEN b.category_id
        END AS category_id
    FROM quotation_line l
    JOIN quotation_annex a ON a.id = l.annex_id
    JOIN quotation_revision rr ON rr.id = a.revision_id
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
    LEFT JOIN ahu_kkb k ON k.line_id = l.id
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
SELECT z.*,
       -- Mahsulot chegirmasi (0025): 1 donaning QQS bilan narxidan (KP valyutasida), natija ROUNDUP(…, 0).
       -- Chegirma bo'lmasa — narx o'zgarmaydi (avvalgi hisob bilan aynan bir xil).
       CASE WHEN z.line_discount_kind = 'pct'    THEN ceil(z.display_unit_price * (1 - z.line_discount_value))
            WHEN z.line_discount_kind = 'amount' THEN ceil(z.display_unit_price - z.line_discount_value)
            ELSE z.display_unit_price END AS display_unit_net,
       CASE WHEN z.line_discount_kind = 'pct'    THEN ceil(z.display_unit_price * (1 - z.line_discount_value))
            WHEN z.line_discount_kind = 'amount' THEN ceil(z.display_unit_price - z.line_discount_value)
            ELSE z.display_unit_price END * z.quantity AS display_line_net
FROM (
SELECT q.*,
       -- Valyuta: bir xil bo'lsa ×1, USD→UZS bo'lsa ×kurs, boshqa yo'nalish NULL (xato yashirinmaydi).
       q.unit_price_incl_vat
         * CASE WHEN q.display_currency = q.price_currency THEN 1
              WHEN q.price_currency = 'USD' AND q.display_currency = 'UZS' THEN q.exchange_rate END AS display_unit_price,
       q.unit_price_incl_vat
         * CASE WHEN q.display_currency = q.price_currency THEN 1
              WHEN q.price_currency = 'USD' AND q.display_currency = 'UZS' THEN q.exchange_rate END
         * q.quantity AS display_line_total,
       ld.kind AS line_discount_kind, ld.value AS line_discount_value, ld.reason AS line_discount_reason
FROM (
    SELECT p.*,
           -- QQS bilan narx: ROUNDUP(marjali × (1 + QQS), 0) yoki manbadagi qat'iy qiymat.
           -- AHU (AHU fayldan yoki "AHU" kategoriyali qator) — HAR DOIM butun songa yuqoriga (foydalanuvchi qarori 2026-10-17),
           -- manbadagi qat'iy qiymat kasrli bo'lsa ham (masalan 42 330 × 1,12 = 47 409,60 -> 47 410).
           CASE WHEN p.line_type = 'ahu' OR p.category_id IN (SELECT id FROM product_category WHERE name = 'AHU')
                THEN ceil(coalesce(p.fixed_price_incl_vat, ceil(p.unit_price_excl_vat * (1 + p.vat_rate))))
                ELSE coalesce(p.fixed_price_incl_vat, ceil(p.unit_price_excl_vat * (1 + p.vat_rate)))
           END AS unit_price_incl_vat
    FROM priced p
) q
LEFT JOIN line_discount ld ON ld.line_id = q.line_id
) z;

-- Ilova jamlari (0025): subtotal — brutto (chegirmasiz); mahsulot chegirmalari; ilova chegirmasi netto (mahsulot chegirmasidan keyingi)
-- summadan; hech biri yaxlitlanmaydi (chegirmali bir dona narxi esa v_line_price da ROUNDUP qilingan).
CREATE VIEW v_annex_totals AS
SELECT a.id AS annex_id, a.revision_id, a.annex_no, a.name,
       count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) AS missing_price_lines,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_total), 0) END AS subtotal,
       coalesce(sum(lp.quantity), 0) AS total_quantity,
       d.discount_pct,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_net), 0) * coalesce(d.discount_pct, 0) END AS discount_amount,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_net), 0) * (1 - coalesce(d.discount_pct, 0)) END AS total_after_discount,
       d.reason AS discount_reason, d.created_by AS discount_by, d.created_at AS discount_at,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_total - lp.display_line_net), 0) END AS line_discount_amount,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_net), 0) END AS net_subtotal
FROM quotation_annex a
LEFT JOIN v_line_price lp ON lp.annex_id = a.id
LEFT JOIN annex_discount d ON d.annex_id = a.id
GROUP BY a.id, a.revision_id, a.annex_no, a.name, d.discount_pct, d.reason, d.created_by, d.created_at;

-- KP jamlari: discount_amount = mahsulot + ilova chegirmalari (subtotal − discount_amount = total_incl_vat)
CREATE VIEW v_quotation_totals AS
SELECT r.id AS revision_id, q.kp_number, r.revision_no, r.status, r.kp_date,
       r.kp_date + r.validity_days AS valid_until,
       r.display_currency,
       count(t.annex_id) AS annex_count,
       coalesce(sum(t.missing_price_lines), 0) AS missing_price_lines,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.subtotal), 0) END AS subtotal,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE
            THEN coalesce(sum(t.discount_amount + t.line_discount_amount), 0) END AS discount_amount,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.total_after_discount), 0) END AS total_incl_vat,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.total_after_discount), 0) / (1 + vr.rate) END AS total_excl_vat_info,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.total_after_discount), 0) - coalesce(sum(t.total_after_discount), 0) / (1 + vr.rate) END AS vat_amount_info,
       r.show_excl_vat_note,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.line_discount_amount), 0) END AS line_discount_amount
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
       t.subtotal, t.discount_pct, t.discount_amount, t.total_after_discount, t.missing_price_lines,
       de.full_name AS discount_by_name, t.discount_at, t.discount_reason,
       t.line_discount_amount
FROM latest l
JOIN quotation q ON q.id = l.quotation_id
JOIN project p ON p.id = q.project_id
JOIN employee e ON e.id = q.manager_id
JOIN v_annex_totals t ON t.revision_id = l.id
LEFT JOIN app_user du ON du.id = t.discount_by
LEFT JOIN employee de ON de.id = du.employee_id;
