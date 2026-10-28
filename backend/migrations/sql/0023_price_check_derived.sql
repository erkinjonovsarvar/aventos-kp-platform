-- 0023 (2026-10-20): narx ro'yxati QQS tekshiruvi aniqlashtirildi. Ma'lumot O'ZGARMAYDI.
-- Foydalanuvchi qarori (2026-10-20, G4 va C010): QQSsiz narx QQS bilan narxdan hisoblangan bo'lsa (QQSsiz = QQS bilan / (1+QQS),
-- yaxlitlanmaydi — CLAUDE.md) — bu ham to'g'ri. Avval tekshiruv ROUNDUP(QQSsiz × 1,12) ni talab qilgani uchun bunday qatorlar
-- (masalan "36 duct": 1624,107142857143 × 1,12 = 1819,0000000000002 → ROUNDUP 1820) xato ko'rinardi.
-- Yangi ustun is_current: narx ro'yxati eng so'nggi tasdiqlangan versiyami (eski versiyalar tarix sifatida ko'rinib turadi).

CREATE OR REPLACE VIEW v_price_list_check AS
SELECT pli.id AS price_list_item_id, pl.name AS price_list, pr.model,
       pli.price_excl_vat, pli.price_incl_vat,
       vr.rate AS vat_rate,
       ceil(pli.price_excl_vat * (1 + vr.rate)) AS expected_incl_vat,
       CASE WHEN vr.rate IS NULL THEN 'TEKSHIRISH KERAK (QQS stavkasi yo''q)'
            WHEN pli.price_incl_vat = ceil(pli.price_excl_vat * (1 + vr.rate)) THEN 'OK'
            WHEN abs(pli.price_excl_vat * (1 + vr.rate) - pli.price_incl_vat) < 0.000001 THEN 'OK'
            ELSE 'TEKSHIRISH KERAK' END AS check_status,
       pl.id = (SELECT p2.id FROM price_list p2 WHERE p2.approved_at IS NOT NULL
                ORDER BY p2.valid_from DESC, p2.id DESC LIMIT 1) AS is_current
FROM price_list_item pli
JOIN price_list pl ON pl.id = pli.price_list_id
JOIN product pr ON pr.id = pli.product_id
LEFT JOIN LATERAL (
    SELECT rate FROM vat_rate WHERE valid_from <= pl.valid_from ORDER BY valid_from DESC LIMIT 1
) vr ON true;
