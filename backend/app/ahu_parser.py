"""AHU zavod fayli (quotation.xlsx, bitta "Sheet") o'quvchisi.

Tuzilma (CLAUDE.md): C4 loyiha nomi, C5 sana; 4 ta blok, har biri sarlavha qatori (A="AHU", F="Unit Price ($)") bilan
boshlanadi va "TOTAL ..." qatorigacha davom etadi:
  AHU            (C="Air Flow")             : A yorliq, C air flow, D model, E soni, F narx
  AUTOMATION     (C="Automation Features")  : blok ichidagi tartibi bo'yicha AHU qatoriga mos (A = AHU yorlig'i), C tavsif, E, F
  VRF + AHU KIT  (D="VRF Outdoor Unit")     : A qaysi AHU uchun, B tur ("AHU Kits" bo'lsa — kit), C quvvat (kW), D model, E, F
  3-WAY VALVES   (B="kg/h")                 : A qaysi AHU uchun, B kg/h, C valve, D actuator, E soni, F narx
Bloklar sarlavha bo'yicha topiladi (2026-10-19: yangi shablonda bloklar 3-4 qatorga siljigan — AHU 9–36, automation
43–67, VRF 72–107, valve 112–139). Sarlavha topilmasa — eski qat'iy qatorlar (9–33 / 40–64 / 69–105 / 110–137).
Yashirin (hidden) qatorlar KP ga kirmaydi (CLAUDE.md). Hech narsa taxmin qilinmaydi: noaniqlik -> warnings.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile
import math
from dataclasses import dataclass, field
from decimal import Decimal

import openpyxl

# Eski (birinchi 6 namunadagi) qat'iy joylashuv — sarlavha topilmasa ishlatiladi
LEGACY = {"AHU": range(9, 34), "AUTOMATION": range(40, 65), "VRF": range(69, 106), "VALVE": range(110, 138)}


@dataclass
class Item:
    row: int
    block: str                       # AHU / AUTOMATION / VRF / KIT / VALVE
    unit_label: str | None
    model: str | None
    description: str | None
    quantity: Decimal
    unit_price: Decimal | None
    air_flow: Decimal | None = None
    flow_kg_h: Decimal | None = None
    capacity_kw: Decimal | None = None
    parent_row: int | None = None    # AHU qatori (AHU dan boshqa bloklar uchun)
    src_label: str | None = None     # VRF/kit/valve qatorining A ustunidagi AHU yorlig'i (bog'lash uchun)


@dataclass
class ParsedOffer:
    file_name: str
    sha256: str
    project_name: str | None
    offer_date: dt.date | None
    items: list[Item] = field(default_factory=list)
    hidden_rows: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_vrf(self) -> bool:
        return any(i.block in ("VRF", "KIT") for i in self.items)


def _num(v) -> Decimal | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return None if math.isnan(v) else Decimal(repr(v))
    if isinstance(v, str):
        try:
            return Decimal(v.strip().replace(",", ".")) if v.strip() else None
        except Exception:
            return None
    return None


def _text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v)
    return s if s.strip() else None


def _key(label: str | None) -> str:
    return " ".join((label or "").split()).lower()


MAX_UNPACKED = 100 * 1024 * 1024      # xlsx ichidagi fayllar ochilgandagi jami hajm (zip-bomba himoyasi)
MAX_RATIO = 200                       # bitta fayl siqilish nisbati


def _check_zip(content: bytes) -> None:
    """Xavfsizlik auditi 2026-10-17: o'qishdan oldin xlsx (zip) ichini tekshirish — juda katta ochiladigan fayl rad etiladi.
    XML hujumlari (billion laughs, tashqi entity) — openpyxl defusedxml orqali o'qiydi (requirements.txt)."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        total = 0
        for i in z.infolist():
            total += i.file_size
            if i.compress_size and i.file_size / i.compress_size > MAX_RATIO and i.file_size > 1024 * 1024:
                raise ValueError(f"fayl ichidagi '{i.filename}' shubhali darajada siqilgan")
        if total > MAX_UNPACKED:
            raise ValueError("fayl ochilganda juda katta (100 MB dan ortiq)")


def _sections(ws) -> dict[str, range]:
    """Blok sarlavhalari (A="AHU", F da "Unit Price") bo'yicha: {blok: ma'lumot qatorlari}; "TOTAL" qatorigacha."""
    found: dict[str, int] = {}
    for r in range(1, ws.max_row + 1):
        if (_text(ws.cell(r, 1).value) or "").strip().upper() != "AHU" or "unit price" not in (_text(ws.cell(r, 6).value) or "").lower():
            continue
        b, c, d = ((_text(ws.cell(r, k).value) or "").lower() for k in (2, 3, 4))
        kind = ("AHU" if "air flow" in c else "AUTOMATION" if "automation" in c else
                "VRF" if "vrf" in d or b == "type" else "VALVE" if "kg/h" in b or "valve" in d else None)
        if kind and kind not in found:
            found[kind] = r
    out: dict[str, range] = {}
    for kind, head in found.items():
        end = head + 1
        while end <= ws.max_row and "total" not in " ".join((_text(ws.cell(end, k).value) or "").lower() for k in (1, 4)):
            end += 1
        out[kind] = range(head + 1, end)
    return out


def parse(content: bytes, file_name: str) -> ParsedOffer:
    _check_zip(content)
    sha = hashlib.sha256(content).hexdigest().upper()
    values = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = values.worksheets[0]
    hidden = sorted(r for r, d in ws.row_dimensions.items() if d.hidden)
    hidden_set = set(hidden)

    raw_date = ws["C5"].value
    offer_date = raw_date.date() if isinstance(raw_date, dt.datetime) else raw_date if isinstance(raw_date, dt.date) else None
    offer = ParsedOffer(file_name, sha, _text(ws["C4"].value), offer_date, hidden_rows=hidden)
    if offer_date is None:
        offer.warnings.append(f"C5: sana o'qilmadi ({raw_date!r})")
    sec = _sections(ws)
    missing = [k for k in LEGACY if k not in sec]
    if missing:
        offer.warnings.append("Fayl tuzilmasida blok sarlavhasi topilmadi (" + ", ".join(missing)
                              + ") — namunadagi qatorlar bilan o'qildi, natijani tekshiring")
    rows = {k: sec.get(k, LEGACY[k]) for k in LEGACY}

    def visible(r: int) -> bool:
        return r not in hidden_set

    # --- AHU
    ahu_by_label: dict[str, int] = {}
    for r in rows["AHU"]:
        if not visible(r) or _text(ws.cell(r, 4).value) is None:
            continue
        qty, price = _num(ws.cell(r, 5).value), _num(ws.cell(r, 6).value)
        label = _text(ws.cell(r, 1).value)
        if not qty:
            offer.warnings.append(f"AHU {r}-qator ({label}): soni (E) yo'q — o'tkazib yuborildi")
            continue
        if price is None:
            offer.warnings.append(f"AHU {r}-qator ({label}): narx (F) yo'q")
        offer.items.append(Item(r, "AHU", label, _text(ws.cell(r, 4).value), None, qty, price,
                                air_flow=_num(ws.cell(r, 3).value)))
        if _key(label) in ahu_by_label:
            offer.warnings.append(f"AHU yorlig'i takrorlangan: '{label}' ({ahu_by_label[_key(label)]} va {r}-qatorlar)")
        ahu_by_label.setdefault(_key(label), r)
    ahu_rows = {i.row for i in offer.items}

    # --- AUTOMATION (AHU qatoriga 1:1 — blok ichidagi tartibi bo'yicha; yorliq bo'lsa u bilan tekshiriladi)
    offset = rows["AUTOMATION"].start - rows["AHU"].start
    labels = {i.row: i.unit_label for i in offer.items if i.block == "AHU"}
    for r in rows["AUTOMATION"]:
        if not visible(r):
            continue
        desc, price = _text(ws.cell(r, 3).value), _num(ws.cell(r, 6).value)
        parent = r - offset
        if desc is None and price is None:
            continue
        a_label = _text(ws.cell(r, 1).value)
        if parent in ahu_rows and a_label and _key(a_label) != _key(labels[parent]) and _key(a_label) in ahu_by_label:
            offer.warnings.append(f"Automation {r}-qator: yorlig'i '{a_label}' — tartib bo'yicha mos AHU '{labels[parent]}' emas, "
                                  f"yorliq bo'yicha bog'landi")
            parent = ahu_by_label[_key(a_label)]
        if parent not in ahu_rows:
            offer.warnings.append(f"Automation {r}-qator: mos AHU qatori ({parent}) yo'q yoki yashirin — o'tkazib yuborildi")
            continue
        qty = _num(ws.cell(r, 5).value) or next(i.quantity for i in offer.items if i.row == parent)
        offer.items.append(Item(r, "AUTOMATION", None, None, desc, qty, price, parent_row=parent))

    def parent_of(label: str | None, r: int, what: str) -> int | None:
        p = ahu_by_label.get(_key(label))
        if p is None:
            offer.warnings.append(f"{what} {r}-qator: '{label}' qaysi AHU ga tegishli ekani topilmadi (AHU yorliqlari: "
                                  + ", ".join(sorted({i.unit_label or '' for i in offer.items if i.block == 'AHU'})) + ")")
        return p

    # --- VRF + AHU KIT
    for r in rows["VRF"]:
        if not visible(r) or _text(ws.cell(r, 4).value) is None:
            continue
        label = _text(ws.cell(r, 1).value)
        kind = (_text(ws.cell(r, 2).value) or "").lower()
        block = "KIT" if "kit" in kind else "VRF"
        qty = _num(ws.cell(r, 5).value)
        if not qty:
            offer.warnings.append(f"VRF {r}-qator: soni (E) yo'q — o'tkazib yuborildi")
            continue
        offer.items.append(Item(r, block, None, _text(ws.cell(r, 4).value), _text(ws.cell(r, 2).value), qty,
                                _num(ws.cell(r, 6).value), capacity_kw=_num(ws.cell(r, 3).value),
                                parent_row=parent_of(label, r, "VRF/kit"), src_label=label))

    # --- 3-WAY VALVES
    for r in rows["VALVE"]:
        if not visible(r) or _text(ws.cell(r, 3).value) is None:
            continue
        label = _text(ws.cell(r, 1).value)
        qty, price = _num(ws.cell(r, 5).value), _num(ws.cell(r, 6).value)
        if not qty:
            offer.warnings.append(f"Valve {r}-qator: soni (E) yo'q — o'tkazib yuborildi")
            continue
        if price is None:
            offer.warnings.append(f"Valve {r}-qator: narx (F) yo'q")
        offer.items.append(Item(r, "VALVE", None, _text(ws.cell(r, 3).value), _text(ws.cell(r, 4).value), qty, price,
                                flow_kg_h=_num(ws.cell(r, 2).value), parent_row=parent_of(label, r, "Valve"), src_label=label))

    if not any(i.block == "AHU" for i in offer.items):
        offer.warnings.append("Faylda ko'rinadigan AHU qatori topilmadi")
    return offer
