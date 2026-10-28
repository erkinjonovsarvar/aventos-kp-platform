-- 0012: AHU qatori tavsifi — AHU ning VRF/AHU kit qatorlari bo'lsa (foydalanuvchi qarori 2026-10-16):
--   model + " " + automation + (1 bo'sh qator) + "с ККБ и AHU kit".
-- Faqat ko'rinishlar qayta yaratiladi (0007 dagi ta'riflar + shu o'zgarish), jadvallar o'zgarmaydi.

DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price, v_price_list_check;

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
ahu_with_vrf AS (   -- AHU ning ko'rinadigan VRF/AHU kit qatorlari bor (2026-10-16: tavsifga "с ККБ и AHU kit")
    SELECT DISTINCT parent_item_id AS ahu_item_id
    FROM ahu_offer_item
    WHERE block_code IN ('VRF', 'KIT') AND NOT is_hidden_row AND parent_item_id IS NOT NULL
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
                                      || coalesce(E'\n\n\n' || vt.text, '')
                                      -- VRF bo'lsa: automation dan keyin 1 bo'sh qator va "с ККБ и AHU kit"
                                      || CASE WHEN hv.ahu_item_id IS NOT NULL THEN E'\n\nс ККБ и AHU kit' ELSE '' END END
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
    LEFT JOIN ahu_with_vrf hv ON hv.ahu_item_id = m.id AND m.block_code = 'AHU'
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
       -- narxi noma'lum qator bo'lsa jami ham noma'lum (NULL) — kichik summa ko'rsatilmaydi
       count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) AS missing_price_lines,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_total), 0) END AS subtotal,
       coalesce(sum(lp.quantity), 0) AS total_quantity,
       d.discount_pct,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_total), 0) * coalesce(d.discount_pct, 0) END AS discount_amount,
       CASE WHEN count(lp.line_id) FILTER (WHERE lp.display_line_total IS NULL) = 0
            THEN coalesce(sum(lp.display_line_total), 0) * (1 - coalesce(d.discount_pct, 0)) END AS total_after_discount,
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
       coalesce(sum(t.missing_price_lines), 0) AS missing_price_lines,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.subtotal), 0) END AS subtotal,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.discount_amount), 0) END AS discount_amount,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.total_after_discount), 0) END AS total_incl_vat,
       -- faqat ma'lumot uchun (pastda): QQSsiz va QQS summasi
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.total_after_discount), 0) / (1 + vr.rate) END AS total_excl_vat_info,
       CASE WHEN bool_and(t.subtotal IS NOT NULL) IS NOT FALSE THEN coalesce(sum(t.total_after_discount), 0) - coalesce(sum(t.total_after_discount), 0) / (1 + vr.rate) END AS vat_amount_info,
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
       t.subtotal, t.discount_pct, t.discount_amount, t.total_after_discount, t.missing_price_lines,
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
