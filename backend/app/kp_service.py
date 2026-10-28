"""KP yaratish va tahrirlash qoidalari (CLAUDE.md "AHU KP ni ... kiritish tartibi").

AHU fayldan KP:
  har bir AHU uchun alohida guruh: AHU -> VRF -> AHU kit -> 3-way valves (avval П1 ning hammasi, keyin П2 ...)
  AHU qatori  = AHU + automation (narxga), marja har qatorda alohida (ROUNDUP(x/(1-m), 0))
  VRF / kit   = narx ro'yxatidan (marjasiz)
  valve       = alohida qator, o'z marjasi bilan
  "Faqat AHU + valve" (VRF yo'q) bo'lsa valve'lar AHU tavsifida ham ko'rsatiladi (narxsiz)
Hech narsa taxmin qilinmaydi: marja berilmaguncha va narxsiz qator bor ekan, KP tasdiqlanmaydi.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .ahu_parser import ParsedOffer

LEGACY_LIMIT = 9_999_999          # 10018916 kabi shubhali raqamlar keyingi raqamni hisoblashga ta'sir qilmasin

# Kasseta ichki bloklari -> dekorativ panel (Original DB dagi KP lar juftligi; foydalanuvchi qoidasi 2026-10-16).
# Kassetaga panel va pult doim; kanalniyga faqat pult; настенныйga hech biri (foydalanuvchi aytmasa).
PANEL_RULES = ((r"^AVC-\d+HJDBA", "HPE-DNK1"), (r"^AVBC-", "HPE-GNK1"),
               (r"^AVY-(07|09|12|15)", "HP-D-NA1"), (r"^AVY-(19|24)", "HP-E-NA1"))
PULT_MODEL = "HYXE-VA01A"
PULT_RULES = (r"^AVC-\d+HJDBA", r"^AVBC-", r"^AVY-", r"^AVD-")


def store_offer(conn: Connection, offer: ParsedOffer, user_id: int) -> int:
    """AHU faylini bazaga (o'zgarmas manba sifatida) yozadi. Shu fayl avval yuklangan bo'lsa — o'sha yozuv qaytadi."""
    no_price = [f"{i.block} {i.row}-qator" for i in offer.items if i.unit_price is None]
    if no_price:   # narx taxmin qilinmaydi va 0 deb yozilmaydi — faylni tuzatib qayta yuklash kerak
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Faylda narxi (F) yo'q qatorlar: " + ", ".join(no_price))
    orphans = [i for i in offer.items if i.block != "AHU" and i.parent_row is None]
    if orphans:    # qaysi AHU ga tegishliligi taxmin qilinmaydi — foydalanuvchi tanlaydi (fixes) yoki faylni tuzatadi
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {
            "message": "AHU ga bog'lanmagan qatorlar: " + ", ".join(f"{i.block} {i.row}-qator" for i in orphans) + ". "
                       + " ".join(w for w in offer.warnings if "topilmadi" in w),
            "orphans": [{"row": i.row, "block": i.block, "label": i.src_label, "model": i.model} for i in orphans],
            "ahu": [{"row": i.row, "label": i.unit_label, "model": i.model} for i in offer.items if i.block == "AHU"]})
    existing = conn.execute(text(
        """SELECT o.id FROM ahu_offer o JOIN source_document s ON s.id = o.source_document_id
           WHERE s.sha256 = :h AND s.sheet_name = ''"""), {"h": offer.sha256}).first()
    if existing:
        return existing.id
    doc = conn.execute(text(
        """INSERT INTO source_document (file_name, sheet_name, sha256, kind, uploaded_by)
           VALUES (:f, '', :h, 'ahu_offer', :u) RETURNING id"""),
        {"f": offer.file_name, "h": offer.sha256, "u": user_id}).scalar_one()
    offer_id = conn.execute(text(
        """INSERT INTO ahu_offer (source_document_id, project_name_raw, offer_date, currency_code)
           VALUES (:d, :p, :dt, 'USD') RETURNING id"""),
        {"d": doc, "p": offer.project_name, "dt": offer.offer_date}).scalar_one()
    ids: dict[int, int] = {}
    for it in sorted(offer.items, key=lambda i: (i.block != "AHU", i.row)):    # avval AHU (ota) qatorlar
        ids[it.row] = conn.execute(text(
            """INSERT INTO ahu_offer_item (ahu_offer_id, source_row, block_code, parent_item_id, unit_label, model,
                                           description, air_flow, flow_kg_h, quantity, unit_price)
               VALUES (:o, :r, :b, :p, :l, :m, :d, :af, :fk, :q, :up) RETURNING id"""),
            {"o": offer_id, "r": it.row, "b": it.block, "p": ids.get(it.parent_row) if it.parent_row else None,
             "l": it.unit_label, "m": it.model, "d": it.description, "af": it.air_flow,
             "fk": it.flow_kg_h, "q": it.quantity, "up": it.unit_price}).scalar_one()
    return offer_id


def lock_numbering(conn: Connection, scope: str, key: int = 0) -> None:
    """Yangi raqam (KP №, loyiha №, ilova №, qator №) max()+1 bilan olinadi — ikki parallel so'rov bir xil raqamni
    olmasligi uchun shu doiradagi (masalan bitta ilova qatorlari) raqamlash tranzaksiya oxirigacha navbatga qo'yiladi.
    pg_advisory_xact_lock — tranzaksiya tugashi bilan o'zi bo'shaydi (2026-10-20)."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:s), CAST(:k AS int))"), {"s": f"aventos:{scope}", "k": key % 2**31})


def next_line_no(conn: Connection, annex_id: int) -> int:
    """Ilovadagi oxirgi qator raqami (qulf bilan); keyingi qator = natija + 1."""
    lock_numbering(conn, "line", annex_id)
    return conn.execute(text("SELECT coalesce(max(line_no), 0) FROM quotation_line WHERE annex_id = :a"),
                        {"a": annex_id}).scalar_one()


def next_annex_no(conn: Connection, revision_id: int) -> int:
    lock_numbering(conn, "annex", revision_id)
    return conn.execute(text("SELECT coalesce(max(annex_no), 0) + 1 FROM quotation_annex WHERE revision_id = :r"),
                        {"r": revision_id}).scalar_one()


def _excel_kp_numbers() -> list[int]:
    """D:/Quotations dagi KP papkalari (Excel'da yaratilgan, platformaga hali import qilinmagan bo'lishi mumkin)."""
    from pathlib import Path

    from .config import settings
    base = Path(settings().quotations_dir) if settings().quotations_dir else None
    if base is None or not base.is_dir():
        return []
    return [int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 7]


def next_kp_number(conn: Connection) -> int:
    """Eng KICHIK bo'sh KP raqami (kp_number_floor dan keyin): bazada ham, D:/Quotations papkalarida ham yo'q.
    O'chirilgan KP raqami HAR DOIM qayta beriladi (foydalanuvchi qarori 2026-10-16)."""
    from .config import settings
    floor = settings().kp_number_floor
    taken = {r[0] for r in conn.execute(text("SELECT kp_number FROM quotation WHERE kp_number > :f AND kp_number <= :lim"),
                                         {"f": floor, "lim": LEGACY_LIMIT})}
    taken.update(n for n in _excel_kp_numbers() if n > floor)
    n = floor + 1
    while n in taken:
        n += 1
    return n


def current_price_item(conn: Connection, model: str):
    """Eng so'nggi TASDIQLANGAN narx ro'yxatidagi model. Katta-kichik harf va chetidagi bo'sh joy farq qilmaydi
    ("avwt-76hkf5 " = AVWT-76HKF5; 2026-10-21 — bazada faqat harfi bilan farq qiladigan modellar yo'qligi tekshirildi)."""
    return conn.execute(text(
        """SELECT i.id, i.description, i.price_excl_vat, p.model FROM price_list_item i
           JOIN price_list pl ON pl.id = i.price_list_id JOIN product p ON p.id = i.product_id
           WHERE upper(btrim(p.model)) = upper(btrim(:m)) AND pl.approved_at IS NOT NULL
           ORDER BY pl.valid_from DESC, pl.id DESC LIMIT 1"""), {"m": model}).first()


def add_custom_line(conn: Connection, annex_id: int, line_no: int, *, description: str, model: str | None,
                    category_id: int | None, quantity, unit: str, price_excl_vat, currency: str) -> int:
    """Narx ro'yxatida yo'q mahsulot: narxni FOYDALANUVCHI beradi (CLAUDE.md — taxmin yo'q); marja qatorda alohida."""
    lid = _line(conn, annex_id, line_no, "custom", quantity, unit)
    conn.execute(text(
        """INSERT INTO quotation_line_custom (line_id, category_id, model, description, unit_price_excl_vat, currency_code)
           VALUES (:l, :c, :m, :d, :p, :cur)"""),
        {"l": lid, "c": category_id, "m": model, "d": description, "p": price_excl_vat, "cur": currency})
    return lid


def merge_target(conn: Connection, annex_id: int, model: str | None, line_type: str, price=None):
    """Takror model (foydalanuvchi qarori 2026-10-21, KP_EXPORT_RULES.md 7-bo'lim): ilovada shu model allaqachon bo'lsa —
    yangi qator ochilmaydi, BIRINCHI uchragan qatoriga yig'iladi (soni qo'shiladi). Chaqiruvchi next_line_no (qulf) dan keyin chaqiradi.
    - AHU ilovasida yig'ilmaydi: har AHU ning kit/valve qatorlari o'z guruhida qoladi.
    - Narx ro'yxati qatori faqat narx ro'yxati qatoriga; qo'lda narxli qator — faqat narxi bir xil qo'lda narxli qatorga."""
    if not model or not model.strip():
        return None
    if conn.execute(text(
            """SELECT 1 FROM v_line_price v LEFT JOIN product_category pc ON pc.id = v.category_id
               WHERE v.annex_id = :a AND (v.line_type = 'ahu' OR pc.name = 'AHU') LIMIT 1"""), {"a": annex_id}).first():
        return None
    for r in conn.execute(text(
            """SELECT l.id, l.line_no, l.quantity, l.line_type, c.unit_price_excl_vat AS price
               FROM quotation_line l JOIN v_line_price v ON v.line_id = l.id
               LEFT JOIN quotation_line_custom c ON c.line_id = l.id
               WHERE l.annex_id = :a AND upper(btrim(v.model)) = upper(btrim(:m)) ORDER BY l.line_no"""),
            {"a": annex_id, "m": model}):
        if r.line_type == line_type and (line_type != "custom" or r.price == price):
            return r
    return None


def merge_into(conn: Connection, target, qty) -> dict:
    """Mavjud qatorga son qo'shish. old_quantity — bekor qilish uchun (oldingi son)."""
    conn.execute(text("UPDATE quotation_line SET quantity = quantity + :q WHERE id = :i"), {"q": qty, "i": target.id})
    return {"line_id": target.id, "line_no": target.line_no, "old_quantity": target.quantity}


def _line(conn, annex_id, line_no, line_type, qty, unit="шт") -> int:
    return conn.execute(text(
        """INSERT INTO quotation_line (annex_id, line_no, line_type, quantity, unit_code)
           VALUES (:a, :n, :t, :q, :u) RETURNING id"""),
        {"a": annex_id, "n": line_no, "t": line_type, "q": qty, "u": unit}).scalar_one()


def _first(rules, model: str):
    return next((r[1] if isinstance(r, tuple) else True for r in rules
                 if re.match(r[0] if isinstance(r, tuple) else r, model or "", re.I)), None)


def accessory_needs(conn: Connection, annex_id: int) -> dict:
    """Ilovadagi kasseta/kanalniy bloklar uchun kerakli panel va pult — bor-yo'qligi bilan.
    panels: [{model, need, have, after_line_no}], pult: {model, need, have}"""
    lines = conn.execute(text(
        """SELECT l.id, l.line_no, l.quantity, btrim(v.model) AS model FROM quotation_line l
           JOIN v_line_price v ON v.line_id = l.id WHERE l.annex_id = :a ORDER BY l.line_no"""), {"a": annex_id}).all()
    have = {}
    for ln in lines:
        have[(ln.model or "").upper()] = have.get((ln.model or "").upper(), Decimal(0)) + ln.quantity
    panels: dict[str, dict] = {}
    pult_need = Decimal(0)
    for ln in lines:
        p = _first(PANEL_RULES, ln.model)
        if p:
            d = panels.setdefault(p, {"model": p, "need": Decimal(0), "have": have.get(p, Decimal(0)), "after_line_no": 0})
            d["need"] += ln.quantity
            d["after_line_no"] = ln.line_no
        if _first(PULT_RULES, ln.model):
            pult_need += ln.quantity
    return {"panels": list(panels.values()),
            "pult": {"model": PULT_MODEL, "need": pult_need, "have": have.get(PULT_MODEL, Decimal(0))}}


def _insert_slot(conn: Connection, annex_id: int, after_no: int) -> int:
    """after_no dan keyingi qatorlarni bittaga suradi va bo'shagan raqamni qaytaradi."""
    conn.execute(text("UPDATE quotation_line SET line_no = line_no + 100000 WHERE annex_id = :a AND line_no > :n"),
                 {"a": annex_id, "n": after_no})
    conn.execute(text("UPDATE quotation_line SET line_no = line_no - 99999 WHERE annex_id = :a AND line_no > 100000"),
                 {"a": annex_id})
    return after_no + 1


def add_accessories(conn: Connection, annex_id: int, panels: bool, pult: bool) -> list[str]:
    """Yetishmagan panel(lar)ni o'z guruhidan keyin, pultni oxiriga qo'shadi (bor bo'lsa — sonini yetkazadi)."""
    lock_numbering(conn, "line", annex_id)                 # qatorlar surilganda parallel qo'shish bo'lmasin
    cats = dict(conn.execute(text("SELECT name, id FROM product_category WHERE name IN ('VRF', 'Контроллер')")).all())
    need = accessory_needs(conn, annex_id)
    done, warnings = [], []
    items = [(p["model"], p["need"], p["have"], p["after_line_no"], cats.get("VRF")) for p in need["panels"]] if panels else []
    if pult:
        pu = need["pult"]
        last = next_line_no(conn, annex_id)
        items.append((pu["model"], pu["need"], pu["have"], last, cats.get("Контроллер")))
    for model, qty_need, qty_have, after, cat in sorted(items, key=lambda x: -x[3]):    # oxiridan — raqamlar surilmasin
        if qty_need <= qty_have:
            continue
        existing = conn.execute(text(
            """SELECT l.id, l.quantity FROM quotation_line l JOIN v_line_price v ON v.line_id = l.id
               WHERE l.annex_id = :a AND upper(btrim(v.model)) = :m ORDER BY l.line_no LIMIT 1"""),
            {"a": annex_id, "m": model.upper()}).first()
        if existing:
            conn.execute(text("UPDATE quotation_line SET quantity = :q WHERE id = :i"),
                         {"q": existing.quantity + (qty_need - qty_have), "i": existing.id})
        else:
            add_price_list_line(conn, annex_id, _insert_slot(conn, annex_id, after), model, qty_need - qty_have, warnings, cat)
        done.append(f"{model} × {qty_need - qty_have}")
    return done + warnings


def add_price_list_line(conn: Connection, annex_id: int, line_no: int, model: str, qty, warnings: list[str],
                        category_id: int | None = None) -> int:
    item = current_price_item(conn, model)
    if item is None:
        # Narx taxmin qilinmaydi: narxsiz qator — KP tasdiqlanmaydi, admin narx ro'yxatiga qo'shishi kerak
        lid = _line(conn, annex_id, line_no, "custom", qty)
        conn.execute(text(
            """INSERT INTO quotation_line_custom (line_id, category_id, model, description, currency_code)
               VALUES (:l, :c, :m, 'Narx ro''yxatida yo''q — TEKSHIRISH KERAK', 'USD')"""),
            {"l": lid, "c": category_id, "m": model})
        warnings.append(f"'{model}' tasdiqlangan narx ro'yxatida yo'q — qator narxsiz qo'shildi (KP tasdiqlanmaydi)")
        return lid
    if category_id is None:
        category_id = suggest_category(conn, model, item.description)
    lid = _line(conn, annex_id, line_no, "price_list", qty)
    conn.execute(text("INSERT INTO quotation_line_price_list (line_id, price_list_item_id, category_id) VALUES (:l, :i, :c)"),
                 {"l": lid, "i": item.id, "c": category_id})
    return lid


def suggest_category(conn: Connection, model: str, item_type: str | None) -> int | None:
    """Kategoriya avtomatik (foydalanuvchi so'rovi 2026-10-16; narx ro'yxatida kategoriya yo'q):
    1) shu model avvalgi KP larda eng ko'p qaysi kategoriyada bo'lgan; 2) bo'lmasa — shu turdagi
    (narx ro'yxati tavsifi, masalan "VRF наружный блок") qatorlarda eng ko'p ishlatilgani. Teng bo'lsa — kichik id."""
    for where, val in (("upper(btrim(v.model)) = upper(btrim(:x))", model), ("btrim(v.description) = btrim(:x)", item_type)):
        if not val:
            continue
        cat = conn.execute(text(
            f"""SELECT v.category_id FROM v_line_price v WHERE v.category_id IS NOT NULL AND {where}
                GROUP BY v.category_id ORDER BY count(*) DESC, v.category_id LIMIT 1"""), {"x": val}).scalar()
        if cat is not None:
            return cat
    return None


def build_lines_from_offer(conn: Connection, annex_id: int, offer_id: int, start: int = 0) -> list[str]:
    """AHU fayl qatorlarini ilovaga qo'shish; start — ilovadagi oxirgi line_no (mavjud KP ga qo'shilganda)."""
    warnings: list[str] = []
    items = conn.execute(text(
        "SELECT * FROM ahu_offer_item WHERE ahu_offer_id = :o AND NOT is_hidden_row ORDER BY source_row"),
        {"o": offer_id}).mappings().all()
    has_vrf = any(i["block_code"] in ("VRF", "KIT") for i in items)
    block_category = dict(conn.execute(text("SELECT code, category_id FROM ahu_block")).all())
    children = lambda parent, block: [i for i in items if i["parent_item_id"] == parent and i["block_code"] == block]
    n = start
    for ahu in (i for i in items if i["block_code"] == "AHU"):
        n += 1
        lid = _line(conn, annex_id, n, "ahu", ahu["quantity"])
        link = text("INSERT INTO quotation_line_ahu_item (line_id, ahu_offer_item_id, include_in_price) VALUES (:l, :i, :p)")
        conn.execute(link, {"l": lid, "i": ahu["id"], "p": True})
        for a in children(ahu["id"], "AUTOMATION"):
            conn.execute(link, {"l": lid, "i": a["id"], "p": True})
        if not has_vrf:                                    # CLAUDE.md: faqat AHU + valve — valve'lar AHU tavsifida ham
            for v in children(ahu["id"], "VALVE"):
                conn.execute(link, {"l": lid, "i": v["id"], "p": False})
        for block in ("VRF", "KIT"):          # CLAUDE.md: VRF qatori I='VRF', AHU kit I='Узел система'
            for v in children(ahu["id"], block):
                n += 1
                add_price_list_line(conn, annex_id, n, v["model"], v["quantity"], warnings, block_category[block])
        for v in children(ahu["id"], "VALVE"):
            n += 1
            vid = _line(conn, annex_id, n, "ahu", v["quantity"])
            conn.execute(link, {"l": vid, "i": v["id"], "p": True})
    orphans = [i for i in items if i["block_code"] != "AHU" and i["parent_item_id"] is None]
    for o in orphans:
        warnings.append(f"{o['source_row']}-qator ({o['block_code']} {o['model']}): AHU ga bog'lanmagan — KP ga kiritilmadi")
    return warnings


def can_access_kp(user, manager_id: int) -> bool:
    """Ko'rish qoidasi bilan bir xil (quotations._scope): kp.view_all — hamma KP, aks holda faqat o'zi menejer bo'lgan KP."""
    return user.can("kp.view_all") or (user.can("kp.view_own") and manager_id == user.employee_id)


def revision_for(conn: Connection, kp_number: int, revision_no: int | None = None, *, user):
    """KP ning (oxirgi yoki berilgan) revisioni. Foydalanuvchi shu KP ni ko'ra olmasa — 404 (KP borligi ham oshkor qilinmaydi).
    2026-10-20: avval tahrirlash/tasdiqlashda menejer tekshirilmas edi — kp.create_edit qo'shimcha ruxsati bo'lgan menejer
    boshqa menejerning qoralama KP sini o'zgartira olardi."""
    r = conn.execute(text(
        """SELECT r.*, q.manager_id FROM quotation_revision r JOIN quotation q ON q.id = r.quotation_id
           WHERE q.kp_number = :kp AND (CAST(:n AS int) IS NULL OR r.revision_no = :n)
           ORDER BY r.revision_no DESC LIMIT 1"""), {"kp": kp_number, "n": revision_no}).mappings().first()
    if r is None or not can_access_kp(user, r["manager_id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "KP topilmadi")
    return r


def require_draft(rev) -> None:
    if rev["status"] != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "KP tasdiqlangan/yuborilgan — o'zgartirish uchun yangi revision yarating")


def approval_problems(conn: Connection, revision_id: int) -> list[str]:
    problems = []
    no_margin = conn.execute(text(
        """SELECT l.line_no, a.annex_no FROM quotation_line l JOIN quotation_annex a ON a.id = l.annex_id
           WHERE a.revision_id = :r AND l.line_type = 'ahu' AND l.margin_pct IS NULL ORDER BY a.annex_no, l.line_no"""),
        {"r": revision_id}).all()
    if no_margin:
        problems.append("Marja kiritilmagan qatorlar: " + ", ".join(f"ilova {x.annex_no} / {x.line_no}" for x in no_margin))
    missing = conn.execute(text(
        "SELECT annex_id, line_no FROM v_line_price WHERE revision_id = :r AND display_line_total IS NULL"),
        {"r": revision_id}).all()
    if missing:
        problems.append(f"Narxi yo'q qatorlar: {len(missing)} ta")
    if not conn.execute(text(
            "SELECT 1 FROM quotation_line l JOIN quotation_annex a ON a.id = l.annex_id WHERE a.revision_id = :r LIMIT 1"),
            {"r": revision_id}).first():
        problems.append("KP da birorta qator yo'q")
    return problems


def copy_revision(conn: Connection, rev, user_id: int) -> int:
    """Yangi revision: oxirgi revisionning to'liq nusxasi (qoralama). Eski revision o'zgarmaydi."""
    new_id = conn.execute(text(
        """INSERT INTO quotation_revision (quotation_id, revision_no, kp_date, validity_days, display_currency,
                                          exchange_rate_id, vat_rate_id, show_excl_vat_note)
           SELECT quotation_id, revision_no + 1, :d, validity_days, display_currency, exchange_rate_id,
                  (SELECT id FROM vat_rate WHERE valid_from <= :d ORDER BY valid_from DESC LIMIT 1), show_excl_vat_note
           FROM quotation_revision WHERE id = :r RETURNING id"""),
        {"r": rev["id"], "d": dt.date.today()}).scalar_one()
    for a in conn.execute(text("SELECT * FROM quotation_annex WHERE revision_id = :r ORDER BY annex_no"),
                          {"r": rev["id"]}).mappings().all():
        na = conn.execute(text(
            """INSERT INTO quotation_annex (revision_id, annex_no, name, application_type_id)
               VALUES (:r, :n, :nm, :t) RETURNING id"""),
            {"r": new_id, "n": a["annex_no"], "nm": a["name"], "t": a["application_type_id"]}).scalar_one()
        d = conn.execute(text("SELECT * FROM annex_discount WHERE annex_id = :a"), {"a": a["id"]}).mappings().first()
        if d:
            conn.execute(text(
                "INSERT INTO annex_discount (annex_id, discount_pct, reason, created_by) VALUES (:a, :p, :r, :u)"),
                {"a": na, "p": d["discount_pct"], "r": d["reason"], "u": user_id})
        for ln in conn.execute(text("SELECT * FROM quotation_line WHERE annex_id = :a ORDER BY line_no"),
                               {"a": a["id"]}).mappings().all():
            nl = conn.execute(text(
                """INSERT INTO quotation_line (annex_id, line_no, line_type, quantity, unit_code, margin_pct)
                   VALUES (:a, :n, :t, :q, :u, :m) RETURNING id"""),
                {"a": na, "n": ln["line_no"], "t": ln["line_type"], "q": ln["quantity"], "u": ln["unit_code"],
                 "m": ln["margin_pct"]}).scalar_one()
            p = {"o": ln["id"], "n": nl}
            conn.execute(text("""INSERT INTO quotation_line_price_list (line_id, price_list_item_id, category_id)
                                 SELECT :n, price_list_item_id, category_id FROM quotation_line_price_list WHERE line_id = :o"""), p)
            conn.execute(text("""INSERT INTO quotation_line_ahu_item (line_id, ahu_offer_item_id, include_in_price)
                                 SELECT :n, ahu_offer_item_id, include_in_price FROM quotation_line_ahu_item WHERE line_id = :o"""), p)
            conn.execute(text("""INSERT INTO quotation_line_custom (line_id, category_id, model, description, performance,
                                     performance_unit, unit_price_excl_vat, price_incl_vat_override, currency_code,
                                     source_document_id, source_row)
                                 SELECT :n, category_id, model, description, performance, performance_unit,
                                        unit_price_excl_vat, price_incl_vat_override, currency_code, source_document_id, source_row
                                 FROM quotation_line_custom WHERE line_id = :o"""), p)
            # mahsulot chegirmasi va uning isboti (0025): chegirma kim bergan bo'lsa, o'shaning nomida qoladi
            conn.execute(text("""INSERT INTO line_discount (line_id, kind, value, reason, created_by)
                                 SELECT :n, kind, value, reason, created_by FROM line_discount WHERE line_id = :o"""), p)
            conn.execute(text("""INSERT INTO discount_evidence_link (evidence_id, line_id, created_by)
                                 SELECT evidence_id, :n, :u FROM discount_evidence_link WHERE line_id = :o"""), {**p, "u": user_id})
        conn.execute(text("""INSERT INTO discount_evidence_link (evidence_id, annex_id, created_by)
                             SELECT evidence_id, :n, :u FROM discount_evidence_link WHERE annex_id = :o"""),
                     {"n": na, "o": a["id"], "u": user_id})
    return new_id
