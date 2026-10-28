-- 0026: 3-way valve qatorida quvvat (kg/h) ko'rsatilmaydi (foydalanuvchi qarori 2026-10-28).
-- Shu vaqtgacha tasdiqlangan revisionlar o'zgarmaydi (kg/h qoladi); qoralamalar va yangi KP lar — performance/unit bo'sh.
-- Ustunlar va turlari 0025 dagidek — CREATE OR REPLACE, bog'liq viewlar qayta yaratilmaydi.

CREATE OR REPLACE VIEW v_line_price AS
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
            WHEN 'ahu' THEN CASE WHEN m.block_code <> 'VALVE' THEN m.air_flow WHEN rr.approved_at < TIMESTAMPTZ '2026-10-28 12:40:00+05' THEN round(m.flow_kg_h) END
        END AS performance,
        CASE l.line_type
            WHEN 'price_list' THEN pli.capacity_unit
            WHEN 'custom'     THEN c.performance_unit
            WHEN 'ahu' THEN CASE WHEN m.block_code <> 'VALVE' THEN 'm3/h' WHEN rr.approved_at < TIMESTAMPTZ '2026-10-28 12:40:00+05' THEN 'kg/h' END
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
