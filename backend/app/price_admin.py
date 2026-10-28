"""Narx ro'yxatini platformaning o'zida yangilash (foydalanuvchi talabi 2026-10-22): yangi mahsulot qo'shish va narx o'zgartirish.

Excel'dan nusxalangan ro'yxat (Ctrl+V) yoki bitta mahsulot formasi -> tekshiruv (yangi / o'zgargan / o'zgarmagan / xato) ->
tasdiqlash. Tasdiqlanganda narx ro'yxatining YANGI versiyasi yaratiladi: oxirgi tasdiqlangan versiyaning barcha qatorlari
ko'chiriladi, o'zgarganlari yangi qiymat bilan yoziladi, yangilari qo'shiladi (C010/C013 bilan bir xil tartib). Eski versiya
o'zgarmaydi (trigger), yuborilgan KP lar o'z narxida qoladi, yangi KP lar eng so'nggi versiyadan narx oladi.

Narx qoidalari (CLAUDE.md, B bo'lim):
- faqat QQS bilan narx berilsa: QQSsiz = QQS bilan / (1 + QQS), yaxlitlanmaydi;
- faqat QQSsiz berilsa: QQS bilan = ROUNDUP(QQSsiz x (1 + QQS), 0);
- ikkalasi berilib, qoidaga mos kelmasa: QQSsiz Excel'da yaxlitlab ko'rsatilgan bo'lsa (farq < 0,01) QQS bilan narxdan
  qayta hisoblanadi, aks holda ikkalasi ham manbadagidek saqlanadi va "TEKSHIRISH KERAK" ogohlantirishi ko'rsatiladi;
- yangi mahsulotda narxsiz qator qabul qilinmaydi (taxmin yo'q).
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .bulk_lines import split_rows, to_num

MAX_ROWS = 1000
MAX_TEXT = 500_000
NO_SERIES = "(seriyasiz)"
NO_BRAND = "(brendsiz)"
TINY = Decimal("0.000001")
FIELDS = ("model", "description", "capacity", "unit", "brand", "series", "price_excl_vat", "price_incl_vat")

# Sarlavha so'zlari — tartib muhim: oldin narx ustunlari ("Цена продажи без НДС" ham "цена" so'zini o'z ichiga oladi)
_HEAD = [
    ("price_excl_vat", ("без ндс", "excluding", "excl", "qqssiz", "ндссиз")),
    ("price_incl_vat", ("с ндс", "including", "incl", "qqs bilan", "ндс билан")),
    ("model", ("модел", "model", "артикул")),
    ("unit", ("ед.", "ед ", "единиц", "unit", "birlik", "kw or", "(изм)")),
    ("capacity", ("мощн", "производ", "capacity", "quvvat", "performance")),
    ("brand", ("бренд", "brand", "марка")),
    ("series", ("сери", "series", "seriya")),
    ("description", ("наимен", "описан", "description", "tavsif", "nomi", "название")),
]
# Sarlavhasiz nusxa: ustunlar soni bo'yicha ma'lum jadval tuzilishi (0 dan boshlab)
_LAYOUTS = {
    "original_db": ({"series": 0, "brand": 1, "capacity": 2, "unit": 3, "model": 6, "description": 8,
                     "price_excl_vat": 9, "price_incl_vat": 10}, "Original DB ('DB 16.05.2026' varag'i: A–K ustunlar)"),
    "price_database": ({"series": 0, "brand": 1, "capacity": 2, "unit": 3, "model": 4, "description": 5,
                        "price_excl_vat": 6, "price_incl_vat": 7}, "Price database ('DATABASE PRICE' jadvali: A–H ustunlar)"),
}


def _clean(v) -> str | None:
    s = " ".join(str(v).split()) if v is not None else ""
    return s or None


def detect_columns(rows: list[list[str]]) -> tuple[dict[str, int], bool, str]:
    """(ustunlar, birinchi qator sarlavhami, tuzilish nomi)."""
    first = [c.lower() for c in rows[0]]
    head: dict[str, int] = {}
    for key, words in _HEAD:
        for i, c in enumerate(first):
            if i not in head.values() and key not in head and c and any(w in c for w in words):
                head[key] = i
    if "model" in head and ("price_excl_vat" in head or "price_incl_vat" in head):
        return head, True, "sarlavha bo'yicha"
    width = max(len(r) for r in rows)
    if width >= 11:
        return dict(_LAYOUTS["original_db"][0]), False, _LAYOUTS["original_db"][1]
    if width == 8:
        return dict(_LAYOUTS["price_database"][0]), False, _LAYOUTS["price_database"][1]
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "Ustunlarni aniqlab bo'lmadi: sarlavha qatori bilan nusxalang (kamida Model va Narx ustunlari) "
                        "yoki Original DB / Price database jadvalidan to'liq qatorlarni nusxalang")


def parse(raw: str) -> dict:
    """Excel matni -> tuzilgan qatorlar (hali tekshirilmagan)."""
    if len(raw) > MAX_TEXT:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Ro'yxat juda katta")
    rows = split_rows(raw)
    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ro'yxat bo'sh")
    cols, header, layout = detect_columns(rows)
    body = rows[1:] if header else rows
    if len(body) > MAX_ROWS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Bir martada ko'pi bilan {MAX_ROWS} qator")
    items = []
    for n, r in enumerate(body, start=2 if header else 1):
        get = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None  # noqa: E731
        item = {"row": n, **{k: _clean(get(k)) for k in FIELDS}}
        if any(item[k] for k in FIELDS):                               # butunlay bo'sh qator o'tkaziladi
            items.append(item)
    return {"items": items, "header": header, "layout": layout, "columns": cols}


def _num(v) -> tuple[Decimal | None, bool]:
    """(qiymat, xato) — bo'sh qiymat xato emas."""
    if v in (None, ""):
        return None, False
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)), False
    d = to_num(str(v))
    return d, d is None


def current_items(conn: Connection) -> dict[str, dict]:
    """Eng so'nggi tasdiqlangan versiyadagi har model: {MODEL(katta harf): {...}}."""
    rs = conn.execute(text(
        """SELECT DISTINCT ON (p.id) p.id AS product_id, p.model, b.name AS brand, s.name AS series, i.description,
                  i.capacity, i.capacity_unit, i.price_excl_vat, i.price_incl_vat
           FROM price_list_item i JOIN price_list pl ON pl.id = i.price_list_id
           JOIN product p ON p.id = i.product_id JOIN product_series s ON s.id = p.series_id JOIN brand b ON b.id = s.brand_id
           WHERE pl.approved_at IS NOT NULL ORDER BY p.id, pl.valid_from DESC, pl.id DESC""")).mappings().all()
    out = {r["model"].strip().upper(): dict(r) for r in rs}
    # narx ro'yxatida hech qachon bo'lmagan, lekin product jadvalida bor modellar (UQ model) — yangi qo'shishda to'qnashmasin
    for r in conn.execute(text(
            """SELECT p.id AS product_id, p.model, b.name AS brand, s.name AS series FROM product p
               JOIN product_series s ON s.id = p.series_id JOIN brand b ON b.id = s.brand_id
               WHERE NOT EXISTS (SELECT 1 FROM price_list_item i WHERE i.product_id = p.id)""")).mappings():
        out.setdefault(r["model"].strip().upper(), {**dict(r), "orphan": True})
    return out


def vat_rate(conn: Connection) -> Decimal:
    r = conn.execute(text("SELECT rate FROM vat_rate WHERE valid_from <= :d ORDER BY valid_from DESC LIMIT 1"),
                     {"d": date.today()}).scalar()
    if r is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "QQS stavkasi kiritilmagan — narx hisoblab bo'lmaydi")
    return Decimal(r)


def _vat_ok(excl: Decimal, incl: Decimal, rate: Decimal) -> bool:
    gross = excl * (1 + rate)
    return incl == Decimal(math.ceil(gross)) or abs(gross - incl) < Decimal("0.000001")


def check(conn: Connection, items: list[dict]) -> dict:
    """Har qatorga holat: new / changed / same / error (+ ogohlantirishlar). Qiymatlar saqlanadigan ko'rinishda qaytadi."""
    rate = vat_rate(conn)
    cur = current_items(conn)
    units = {r[0] for r in conn.execute(text("SELECT code FROM unit WHERE kind = 'performance'"))}
    units_ci = {u.lower(): u for u in units}
    brands = {r[0].lower(): r[0] for r in conn.execute(text("SELECT name FROM brand"))}
    seen: dict[str, int] = {}
    out = []
    for it in items:
        it = {k: _clean(it.get(k)) if k not in ("row",) else it.get(k) for k in ("row", *FIELDS)}
        errors, warnings, changes = [], [], []
        model = it["model"]
        key = model.upper() if model else None
        old = cur.get(key) if key else None
        if not model:
            errors.append("Model yozilmagan")
        elif len(model) > 200:
            errors.append("Model nomi juda uzun")
        elif key in seen:
            errors.append(f"Model ro'yxatda takrorlangan ({seen[key]}-qator bilan) — bittasini qoldiring")
        if key:
            seen.setdefault(key, it["row"])

        excl, bad_e = _num(it["price_excl_vat"])
        incl, bad_i = _num(it["price_incl_vat"])
        cap, bad_c = _num(it["capacity"])
        if bad_e or bad_i:
            errors.append("Narx son emas")
        if bad_c:
            errors.append("Quvvat son emas")
        if (excl is not None and excl < 0) or (incl is not None and incl < 0):
            errors.append("Narx manfiy bo'lishi mumkin emas")
        unit = it["unit"]
        if unit is not None:
            unit = units_ci.get(unit.lower().replace("м3/ч", "m3/h").replace("квт", "kw").replace("кг/ч", "kg/h"))
            if unit is None:
                errors.append(f"Birlik '{it['unit']}' noma'lum (mumkin: {', '.join(sorted(units))})")

        note_excl = None
        if not errors:
            if excl is None and incl is not None:
                excl, note_excl = incl / (1 + rate), "QQSsiz narx QQS bilan narxdan hisoblandi (÷1,12)"
            elif incl is None and excl is not None:
                incl = Decimal(math.ceil(excl * (1 + rate)))
                warnings.append("QQS bilan narx hisoblandi: ROUNDUP(QQSsiz × 1,12)")
            elif excl is not None and incl is not None and not _vat_ok(excl, incl, rate):
                if abs(excl - incl / (1 + rate)) < Decimal("0.01"):
                    excl, note_excl = incl / (1 + rate), "QQSsiz narx QQS bilan narxdan aniq hisoblandi (Excel'da yaxlitlangan)"
                else:
                    warnings.append(f"TEKSHIRISH KERAK: QQSsiz {excl} × 1,12 = {excl * (1 + rate):.2f}, QQS bilan {incl}")
        if note_excl:
            warnings.append(note_excl)

        status_ = "error" if errors else None
        if not errors and (old is None or old.get("orphan")):
            if excl is None:
                errors.append("Yangi mahsulot uchun narx kerak (QQSsiz yoki QQS bilan)")
            if not it["description"]:
                warnings.append("Tavsif (Наименование) yo'q — KP da faqat model ko'rinadi")
            if old and old.get("orphan"):
                warnings.append("Bu model bazada bor (narx ro'yxatidan tashqari) — narx ro'yxatiga qo'shiladi")
            elif it["brand"] and it["brand"].lower() not in brands:
                warnings.append(f"Yangi brend: {it['brand']}")
            status_ = "error" if errors else "new"
        elif not errors:
            # ÷1,12 natijasi bazadagi bilan juda kichik xonalarda farq qilishi mumkin (Decimal vs numeric) — bu o'zgarish emas
            if excl is not None and old["price_excl_vat"] is not None and abs(excl - Decimal(old["price_excl_vat"])) < TINY:
                excl = Decimal(old["price_excl_vat"])
            fields = {"description": it["description"], "capacity": cap, "capacity_unit": unit,
                      "price_excl_vat": excl, "price_incl_vat": incl}
            for f, v in fields.items():
                if v is not None and (old[f] is None or (Decimal(old[f]) != v if isinstance(v, Decimal) else old[f] != v)):
                    changes.append({"field": f, "old": old[f], "new": v})
            if (it["brand"] and it["brand"].lower() != (old["brand"] or "").lower()) or \
               (it["series"] and it["series"].lower() != (old["series"] or "").lower()):
                warnings.append(f"Brend/seriya o'zgarmaydi (bazada: {old['brand']} / {old['series']})")
            status_ = "changed" if changes else "same"
        out.append({
            **it, "status": status_, "errors": errors, "warnings": warnings, "changes": changes,
            "value": None if errors else {
                "model": model, "description": it["description"] if it["description"] is not None else (old or {}).get("description"),
                "capacity": cap if cap is not None else (old or {}).get("capacity"),
                "capacity_unit": unit if unit is not None else (old or {}).get("capacity_unit"),
                "price_excl_vat": excl if excl is not None else (old or {}).get("price_excl_vat"),
                "price_incl_vat": incl if incl is not None else (old or {}).get("price_incl_vat"),
                "brand": (old or {}).get("brand") if old and not old.get("orphan") else (it["brand"] or NO_BRAND),
                "series": (old or {}).get("series") if old and not old.get("orphan") else (it["series"] or NO_SERIES),
                "product_id": (old or {}).get("product_id"),
            },
            "old": None if not old or old.get("orphan") else {
                "description": old["description"], "capacity": old["capacity"], "capacity_unit": old["capacity_unit"],
                "price_excl_vat": old["price_excl_vat"], "price_incl_vat": old["price_incl_vat"],
                "brand": old["brand"], "series": old["series"]},
        })
    counts: dict[str, int] = {}
    for o in out:
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    return {"items": out, "counts": counts, "vat_rate": rate}


def _id(conn: Connection, sql: str, **p) -> int | None:
    return conn.execute(text(sql), p).scalar()


def apply(conn: Connection, items: list[dict], user_id: int, name: str | None, source_label: str) -> dict:
    """Tekshiruvdan o'tgan qatorlar bilan yangi tasdiqlangan versiya. Xato bo'lsa — hech narsa yozilmaydi."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('aventos:price_list'), 0)"))   # bir vaqtda ikki versiya bo'lmasin
    res = check(conn, items)
    bad = [i for i in res["items"] if i["status"] == "error"]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": f"{len(bad)} ta qatorda xato — tuzating yoki olib tashlang", "rows": [i["row"] for i in bad]})
    todo = [i for i in res["items"] if i["status"] in ("new", "changed")]
    if not todo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "O'zgarish yo'q — barcha qatorlar narx ro'yxatidagidek")
    old = conn.execute(text("SELECT id, name FROM price_list WHERE approved_at IS NOT NULL "
                            "ORDER BY valid_from DESC, id DESC LIMIT 1")).mappings().first()

    payload = "\n".join("\t".join(str(i["value"][k] or "") for k in ("model", "price_excl_vat", "price_incl_vat")) for i in todo)
    sha = hashlib.sha256(f"{user_id}|{datetime.now().isoformat()}|{payload}".encode()).hexdigest().upper()
    doc = _id(conn, """INSERT INTO source_document (file_name, sheet_name, sha256, kind, uploaded_by)
                       VALUES (:f, '', :s, 'price_list', :u) RETURNING id""", f=source_label[:200], s=sha, u=user_id)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_count = sum(1 for i in todo if i["status"] == "new")
    title = (name or "").strip() or f"Platforma: +{new_count} yangi, {len(todo) - new_count} o'zgargan ({stamp})"
    new_id = _id(conn, "INSERT INTO price_list (name, valid_from, source_document_id) VALUES (:n, :d, :doc) RETURNING id",
                 n=title[:300], d=date.today(), doc=doc)

    changed_ids = [i["value"]["product_id"] for i in todo if i["status"] == "changed"]
    copied = 0
    if old:
        copied = conn.execute(text(
            """INSERT INTO price_list_item (price_list_id, product_id, category_id, description, capacity, capacity_unit,
                                            currency_code, price_excl_vat, price_incl_vat, source_row)
               SELECT :new, product_id, category_id, description, capacity, capacity_unit, currency_code,
                      price_excl_vat, price_incl_vat, source_row
               FROM price_list_item WHERE price_list_id = :old AND NOT (product_id = ANY(:skip))"""),
            {"new": new_id, "old": old["id"], "skip": changed_ids}).rowcount

    for i in todo:
        v = i["value"]
        pid = v["product_id"]
        category = None
        if i["status"] == "changed" and old:
            category = _id(conn, "SELECT category_id FROM price_list_item WHERE price_list_id = :o AND product_id = :p",
                           o=old["id"], p=pid)
        if pid is None:
            brand = _id(conn, "SELECT id FROM brand WHERE lower(name) = lower(:n)", n=v["brand"]) or \
                _id(conn, "INSERT INTO brand (name) VALUES (:n) RETURNING id", n=v["brand"])
            series = _id(conn, "SELECT id FROM product_series WHERE brand_id = :b AND lower(name) = lower(:n)", b=brand, n=v["series"]) or \
                _id(conn, "INSERT INTO product_series (brand_id, name) VALUES (:b, :n) RETURNING id", b=brand, n=v["series"])
            pid = _id(conn, "INSERT INTO product (model, series_id) VALUES (:m, :s) RETURNING id", m=v["model"], s=series)
        conn.execute(text(
            """INSERT INTO price_list_item (price_list_id, product_id, category_id, description, capacity, capacity_unit,
                                            currency_code, price_excl_vat, price_incl_vat, source_row)
               VALUES (:l, :p, :c, :d, :cap, :u, 'USD', :e, :i, :r)"""),
            {"l": new_id, "p": pid, "c": category, "d": v["description"], "cap": v["capacity"], "u": v["capacity_unit"],
             "e": v["price_excl_vat"], "i": v["price_incl_vat"], "r": max(int(i["row"] or 1), 1)})
    conn.execute(text("UPDATE price_list SET approved_by = :u, approved_at = now() WHERE id = :id"), {"u": user_id, "id": new_id})
    return {"price_list_id": new_id, "name": title, "copied": copied, "added": new_count,
            "changed": len(todo) - new_count, "previous": dict(old) if old else None}
