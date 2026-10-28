"""Excel'dan nusxalangan ro'yxatni (Model / Soni / Narx) KP ilovasiga ommaviy qo'shish (foydalanuvchi talabi 2026-10-19).

Excel'dan Ctrl+C -> Ctrl+V: qatorlar "\\n", ustunlar "\\t" bilan ajratilgan matn. Tahlil:
- MODEL ustuni katalog bo'yicha tanlanadi: qaysi ustun qiymatlari ko'proq katalogdan topilsa — o'sha (KP jadvalini butunligicha
  "Тип продукта | Наименование | Модель | ..." bilan nusxalasa ham to'g'ri ustun olinadi);
- SONI — "Кол-во / Soni / Qty" sarlavhali yoki harfsiz butun sonli ustun ("3,6kw" quvvat ustuni son hisoblanmaydi);
- NARX — faqat "Цена / Narx / Price" sarlavhasi bo'lsa;
- moslash: aniq -> "found"; bitta modelga aniq mos keladigan yozilish farqi (bo'sh joy, chiziqcha, kirill harf, qo'shimchasiz
  nom HFPE-238K4M22 -> HFPE-238K4M22/E, matn ichidagi model) -> "corrected" (avtomatik, tasdiq shart emas);
  bir nechta nomzod yoki taxminiy o'xshashlik -> "similar" (foydalanuvchi tanlaydi); yo'q -> "not_found" (narxni foydalanuvchi
  yozadi — taxmin yo'q); soni noto'g'ri -> "error";
- bir xil model takrorlansa, soni qo'shiladi (o'chirib qo'yish mumkin).
"""
from __future__ import annotations

import difflib
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.engine import Connection

MAX_ROWS = 300
MAX_TEXT = 100_000
MIN_PREFIX = 6                                   # qo'shimchasiz nom bo'yicha moslash uchun eng kam uzunlik

# Kirill harflari lotinga o'xshash (Excel'da adashib yozilgan modellar uchun) — faqat solishtirishda
_LOOKALIKE = str.maketrans("АВЕКМНОРСТХУаеокмнорстху", "ABEKMHOPCTXYAEOKMHOPCTXY")
_HEAD = {
    "model": ("модел", "model", "артикул"),
    "qty": ("кол-во", "кол.", "количество", "qty", "quant", "soni", "count"),
    "price": ("цена", "price", "narx"),
}
_QTY_RE = re.compile(r"^-?[\d\s.,]+\s*(шт\.?|pcs|dona|ta)?$", re.I)


def norm(model: str) -> str:
    """Solishtirish kaliti: katta harf, kirill->lotin, bo'sh joy va - _ . belgilarsiz."""
    return re.sub(r"[\s\-_.]+", "", (model or "").translate(_LOOKALIKE).upper())


def to_num(cell: str | None) -> Decimal | None:
    """'1 234,50' / '1,234.50' / '12' / '15 шт' -> Decimal; harfli qiymat ('3,6kw', 'AVS-12') -> None."""
    s = (cell or "").strip().replace(" ", " ")
    if not s or not _QTY_RE.match(s):
        return None
    s = re.sub(r"[^\d.,\-]", "", s)
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def split_rows(raw: str) -> list[list[str]]:
    lines = [ln for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
    if any("\t" in ln for ln in lines):
        return [[c.strip() for c in ln.split("\t")] for ln in lines]
    out = []                                             # ustunlarsiz: "AVS-12HJDTD 15" yoki "AVS-12HJDTD;15"
    for ln in lines:
        parts = [p for p in re.split(r"[;|]", ln) if p.strip()] if re.search(r"[;|]", ln) else None
        if parts is None:
            m = re.match(r"^(.*?)\s+([\d\s.,]+)$", ln.strip())
            parts = [m.group(1), m.group(2)] if m else [ln.strip()]
        out.append([p.strip() for p in parts])
    return out


def catalog(conn: Connection) -> dict[str, dict]:
    """Tasdiqlangan narx ro'yxatidagi har modelning oxirgi narxi: {model: {...}}."""
    rs = conn.execute(text(
        """SELECT DISTINCT ON (p.model) p.model, btrim(i.description) AS type, i.capacity, i.capacity_unit,
                  i.price_excl_vat, i.price_incl_vat
           FROM price_list_item i JOIN price_list pl ON pl.id = i.price_list_id JOIN product p ON p.id = i.product_id
           WHERE pl.approved_at IS NOT NULL ORDER BY p.model, pl.valid_from DESC, pl.id DESC""")).mappings().all()
    return {r["model"]: dict(r) for r in rs}


class Matcher:
    """Katalog bo'yicha model qidirish: (holat, model, nomzodlar)."""

    def __init__(self, cat: dict[str, dict]):
        self.cat = cat
        self.by_upper = {m.upper().strip(): m for m in cat}
        self.by_norm: dict[str, list[str]] = {}
        for m in cat:
            self.by_norm.setdefault(norm(m), []).append(m)
        self.norm_keys = sorted(self.by_norm)

    def _strict(self, s: str) -> list[str]:
        """Aniq yoki faqat yozilishi farq qiladigan (bo'sh joy/chiziqcha/kirill) nomzodlar."""
        e = self.by_upper.get(s.upper().strip())
        return [e] if e else list(self.by_norm.get(norm(s), []))

    def _prefix(self, n: str) -> list[str]:
        """Qo'shimchasiz nom: katalogdagi model shu bilan boshlanadi (HFPE238K4M22 -> HFPE238K4M22/E)
        yoki yozilgan nom katalogdagi model + qo'shimcha (AVS12HJDTD-W -> AVS12HJDTD)."""
        if len(n) < MIN_PREFIX:
            return []
        longer = [k for k in self.norm_keys if k.startswith(n) and k != n and not k[len(n)].isalnum()] or \
                 [k for k in self.norm_keys if k.startswith(n) and k != n]
        if longer:
            return [m for k in sorted(longer, key=len) for m in self.by_norm[k]]
        shorter = [k for k in self.norm_keys if len(k) >= MIN_PREFIX and n.startswith(k) and not n[len(k)].isalnum()]
        return [m for k in sorted(shorter, key=len, reverse=True)[:1] for m in self.by_norm[k]]

    def resolve(self, raw: str) -> tuple[str, str | None, list[str]]:
        raw = raw.strip()
        e = self.by_upper.get(raw.upper())
        if e:
            return "found", e, [e]
        tokens = [raw] + [t for t in re.split(r"[\s()\[\],;:]+", raw) if len(t) >= 4 and re.search(r"\d", t)]
        for t in tokens:                                           # yozilish farqi yoki matn ichidagi model
            c = self._strict(t)
            if len(c) == 1:
                return ("found" if t.upper() == c[0].upper() else "corrected"), c[0], c
            if c:
                return "similar", c[0], c
        for t in tokens:                                           # qo'shimchasiz / qo'shimchali nom
            c = self._prefix(norm(t))
            if len(c) == 1:
                return "corrected", c[0], c
            if c:
                return "similar", c[0], c[:5]
        close = difflib.get_close_matches(norm(raw), self.norm_keys, n=3, cutoff=0.8)
        c = [m for k in close for m in self.by_norm[k]]
        return ("similar", c[0], c[:5]) if c else ("not_found", None, [])


def detect_columns(rows: list[list[str]], matcher: Matcher | None = None) -> tuple[dict[str, int], bool]:
    """(ustunlar, birinchi qator sarlavhami). Model ustuni — katalogdan eng ko'p topiladigan ustun."""
    first = [c.lower() for c in rows[0]]
    head: dict[str, int] = {}
    for key, words in _HEAD.items():
        for i, c in enumerate(first):
            if i not in head.values() and any(w in c for w in words) and to_num(c) is None:
                head[key] = i
                break
    has_header = bool(head) and all(to_num(c) is None for c in rows[0] if c)
    data = rows[1:] if has_header else rows
    width = max(len(r) for r in rows)

    def vals(i: int) -> list[str]:
        return [r[i] for r in data if i < len(r) and r[i]]

    def hit_rate(i: int) -> float:
        v = vals(i)
        if not v:
            return 0.0
        if matcher is None:                                         # katalogsiz: harf+raqamli matn
            return sum(bool(re.search(r"[A-Za-zА-Яа-я]", x) and re.search(r"\d", x)) for x in v) / len(v)
        return sum(matcher.resolve(x)[0] in ("found", "corrected") for x in v) / len(v)

    def numeric(i: int) -> float:
        v = vals(i)
        return sum(to_num(x) is not None for x in v) / len(v) if v else 0.0

    scores = {i: hit_rate(i) for i in range(width)}
    best = max(range(width), key=lambda i: (scores[i], i == head.get("model"), -i))
    model = head["model"] if "model" in head and scores[head["model"]] >= scores[best] - 0.1 else best
    cols = {"model": model}
    if "qty" in head and head["qty"] != model:
        cols["qty"] = head["qty"]
    else:
        nums = [i for i in range(width) if i != model and numeric(i) >= 0.8]
        ints = [i for i in nums if all(to_num(x) == to_num(x).to_integral() for x in vals(i) if to_num(x) is not None)]
        pick = ([i for i in ints if i > model] or ints or [i for i in nums if i > model] or nums)
        if pick:
            cols["qty"] = pick[0]
    if "price" in head and head["price"] not in cols.values():
        cols["price"] = head["price"]
    return cols, has_header


def _plain(d: dict | None) -> dict | None:
    if d is None:
        return None
    return {k: (format(v.normalize(), "f") if isinstance(v, Decimal) else v) for k, v in d.items()}


def preview(conn: Connection, raw: str, merge: bool = True) -> dict:
    if len(raw) > MAX_TEXT:
        raise ValueError("Matn juda katta (100 000 belgidan ko'p)")
    rows = split_rows(raw)
    if not rows:
        raise ValueError("Ro'yxat bo'sh — Excel'dan Model va Soni ustunlarini nusxalab joylang")
    cat = catalog(conn)
    matcher = Matcher(cat)
    cols, has_header = detect_columns(rows, matcher)
    data = rows[1:] if has_header else rows
    if len(data) > MAX_ROWS:
        raise ValueError(f"Bir martada ko'pi bilan {MAX_ROWS} qator")

    items: list[dict] = []
    merged: dict[tuple, dict] = {}
    for n, r in enumerate(data, start=2 if has_header else 1):
        cell = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else ""   # noqa: E731
        model_raw = cell("model").strip()
        if not model_raw or model_raw.lower() in ("итого", "jami", "всего"):
            continue
        qty, price = to_num(cell("qty")), to_num(cell("price"))
        status, model, cands = matcher.resolve(model_raw)
        it = {"row": n, "model_raw": model_raw, "quantity": qty, "price": price, "status": status, "model": model,
              "match": cat.get(model) if model else None, "error": None,
              "suggestions": [_plain({"model": c, **cat[c]}) for c in cands] if status in ("similar", "corrected") else []}
        if qty is None or qty <= 0:
            it["status"], it["error"] = "error", f"Soni noto'g'ri: {cell('qty')!r}" if cell("qty") else "Soni yo'q"
        key = (it["model"] or norm(model_raw), str(price))
        if merge and it["status"] != "error" and key in merged:
            merged[key]["quantity"] += qty
            merged[key]["merged_rows"].append(n)
            continue
        it["merged_rows"] = [n]
        if merge and it["status"] != "error":
            merged[key] = it
        items.append(it)

    out = []
    for it in items:
        out.append({**it, "quantity": format(it["quantity"].normalize(), "f") if it["quantity"] is not None else None,
                    "price": format(it["price"], "f") if it["price"] is not None else None, "match": _plain(it["match"])})
    counts = {s: sum(1 for i in out if i["status"] == s) for s in ("found", "corrected", "similar", "not_found", "error")}
    # narx ustuni sarlavhasi "с НДС" bo'lsa — QQS bilan (katalogda yo'q qatorga QQSsiz narx = narx / 1,12 sifatida taklif qilinadi)
    ph = (rows[0][cols["price"]].lower() if has_header and "price" in cols and cols["price"] < len(rows[0]) else "")
    price_vat = "incl" if re.search(r"(с|c)\s*ндс|incl|bilan", ph) else ("excl" if ph else None)
    return {"columns": cols, "header": has_header, "items": out, "counts": counts, "price_vat": price_vat}
