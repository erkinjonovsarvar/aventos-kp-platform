"""KP ni Excel'ga chiqarish (KP_EXPORT_RULES.md, foydalanuvchi qarorlari 2026-10-15).

Shablon: app/templates/kp_template.xlsx — asosiy "Quotation (AVENTOS&Hisense)" varag'idan (build_kp_template.ps1).
Fayl XML darajasida to'ldiriladi (blank rasmlari, shakllar va formatlash aynan saqlanadi; Excel dasturi kerak emas).

Tuzilma: H52 KP №, H53 loyiha №, H54 sana, B60 loyiha, B61 menejer;
ilova bloklari s = 68 + 83·b (b = 0..11): I{s} ilova №, B{s+1} sarlavha, qatorlar s+4..s+81 (78 ta), Итого s+82;
pastki qism: 1072 Общая стоимость (2+ ilova), 1073–1076 chegirma qatorlari va "Итого со скидкой", 1079 valyuta, 1083 kafolat.
Bo'sh qatorlar o'chirilmaydi — yashiriladi (Hide). Formulalar yo'q — barcha qiymatlar bazadan hisoblangan.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import re
import zipfile
from decimal import Decimal
from pathlib import Path

from lxml import etree
from sqlalchemy import text
from sqlalchemy.engine import Connection

TEMPLATE = Path(__file__).parent / "templates" / "kp_template.xlsx"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
N = f"{{{NS}}}"
BLOCK_START, BLOCK_SIZE, BLOCKS, LINES_PER_BLOCK = 68, 83, 12, 78
FOOTER_TOTAL, FOOTER_FREE = 1072, (1073, 1074, 1075, 1076)
SPACER_ROWS = range(1064, 1072)
# Izoh (Примечание) dan KP da ko'rsatilmaydigan qatorlar — foydalanuvchi namunasi (2026-10-15):
# 1082 "Условия поставки: Самовывоз…", 1084 "Оформление комплексной страховки…", 1085 "Дополнительные услуги по сборке…"
HIDDEN_NOTE_ROWS = (1082, 1084, 1085)
WARRANTY = ("Гарантия: {years}с даты отгрузки товара в нормалных условиях эксплуатации. Повреждения возникшие на строительный "
            "площадке до запуска, во время транпортировки при скачки напряжения или эксплуатационные неисправности, "
            "не подлежит гарантии;")
DESC_CHARS_PER_LINE = 48      # C ustuni kengligi ~55 belgi (Calibri), qatorlar sonini hisoblash uchun
# Yangi muqova (kp_pdf.cover_jpeg) 1-sahifada jadval bilan bir xil chegarada turishi uchun (foydalanuvchi talabi 2026-10-17):
# muqova bo'yi = 1–68-qatorlar (1333,2 pt, qator balandligi o'zgarmaydi) -> eni 1333,2 / 1,4144 = 942,6 pt.
# Jadval eni (B–I, 981,6 pt) shunga tenglashtiriladi: keng ustunlar B (tur) va C (tavsif) biroz toraytiriladi.
COVER_ROWS = 68
COVER_COL_WIDTHS = {2: 26.0, 3: 51.140625}              # B, C (avval 29,44 va 54,89)
DESC_CHARS_COVER = 45                                   # C toraygani uchun qatordagi belgilar soni mos ravishda
LINE_HEIGHT_PT = 16.8          # Montserrat 11 da bir qator (Excel AutoFit bilan o'lchandi, 2026-10-17; 15 da matn kesilardi)
MIN_ROW_HEIGHT = 18.6


class ExportError(Exception):
    pass


# Mahsulot guruhlari (KP_EXPORT_RULES.md 7-bo'lim, 100 ta yuborilgan KP tahlili va foydalanuvchi qarorlari 2026-10-21):
# bitta guruh qatorlarida B ("Тип продукта") birlashtiriladi — keyin mahsulot rasmi shu katakka qo'yiladi.
AHU_PART_CATEGORIES = {"VRF", "Узел система", "Аксесуары", "AHU", "Фильтр"}   # AHU qatoridan keyin unga tegishli qatorlar
ATTACH_CATEGORIES = {"Панель вб VRF", "Панель фанкоила", "Фильтр"}            # o'zidan oldingi blok guruhiga qo'shiladi
CONTROLLER_CATEGORY = "Контроллер"                                             # har pult alohida katakda
GROUP_BY_CATEGORY = {"Рефнет"}                                                 # tavsifi har xil bo'lsa ham bitta guruh
FAN_CATEGORIES = {"Вентилятор", "Fan Filter Unit"}                             # ventilyatorlar — ishlab chiqaruvchi bo'yicha
VALVE_MODEL = re.compile(r"^T[LF]\d{2}")                                       # TL32 TW600, TF80 TW3000 (eski KP da kategoriyasiz)
AHU_MODEL = re.compile(r"^(П|AHU)", re.IGNORECASE)                             # П1, ПВ3, П-1, AHU 1 (eski KP da kategoriyasiz)


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _is_ahu_unit(ln) -> bool:
    if ln.get("performance_unit") != "m3/h" or ln.get("category") in FAN_CATEGORIES:
        return False
    return ln.get("category") == "AHU" or bool(AHU_MODEL.match((ln.get("model") or "").strip()))


def _is_ahu_part(ln) -> bool:
    return ln.get("category") in AHU_PART_CATEGORIES or bool(VALVE_MODEL.match((ln.get("model") or "").strip().upper()))


def _is_attachment(ln) -> bool:
    d = _norm(ln.get("description"))
    return ln.get("category") in ATTACH_CATEGORIES or d.startswith("панель") or d == "фильтр"


def _series_key(ln) -> str:
    """Narx ro'yxatidagi seriya; yo'q bo'lsa (qo'lda kiritilgan qator) — modeldagi raqamlarsiz shakl (AVW-#HKFH#N#)."""
    if ln.get("series"):
        return _norm(ln["series"])
    return re.sub(r"\d+", "#", (ln.get("model") or "").upper())


def _kind(ln) -> tuple:
    """Mahsulot turi — guruh kaliti. Kategoriya emas, tavsifdagi tur (eski KP larda kategoriya bo'sh yoki boshqacha bo'ladi)."""
    d = _norm(ln.get("description"))
    model = (ln.get("model") or "").strip()
    if VALVE_MODEL.match(model.upper()):                    # faqat valve'lardan iborat ilova
        return ("valve",)
    if ln.get("category") in FAN_CATEGORIES or re.search(r"\bfan\b", d):
        return ("fan", "вентс" if model.lower().startswith("вентс") else "")
    if ln.get("category") in GROUP_BY_CATEGORY or not d:
        return ("cat", ln.get("category"))
    fcu = "фанкоил" in d or ln.get("category") == "Фанкоил"
    vrf = "vrf" in d                                        # VRF ichki bloki oddiy split bilan bir guruhga tushmasin
    if "наружный блок" in d:
        return ("outdoor", _series_key(ln))
    if "касет" in d or "кассет" in d:
        size = "mini" if "мини" in d else "1" if "одно" in d else "2" if "двух" in d else "4"
        return ("cassette", size, fcu, vrf)
    if "канальн" in d or "скрыт" in d:
        return ("ducted", fcu, vrf)
    for word in ("настенн", "напольно-потолоч", "сплит"):
        if word in d:
            return (word, fcu, vrf)
    return ("desc", d)


def merge_groups(rows) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Ilova qatorlarini mahsulot guruhlariga ajratadi (KP_EXPORT_RULES.md 7-bo'lim). Natija: (B, C) — birlashtiriladigan
    (birinchi, oxirgi indeks) juftliklari, faqat 2+ qatorli.
    AHU bo'limi (AHU qatori + keyingi VRF/kit/valve qatorlari — har AHU guruhi):
      - qo'shimcha qatori bor AHU — B va C shu AHU guruhi bo'ylab (har AHU alohida, VRF/kit bo'lsa ham — qaror 2026-10-21);
      - qo'shimchasiz ketma-ket AHU lar — B bitta katakda (C yo'q).
    Boshqa qatorlar: mahsulot turi bir xil bo'lsa bitta guruh (tashqi bloklar seriya bo'yicha, mini/standart kasseta alohida);
    panel va filtr o'zidan oldingi blok guruhiga; har pult alohida."""
    n = len(rows)
    groups: list[list] = []                       # [boshi, oxiri, turi, kalit]
    k = 0
    while k < n:
        ln = rows[k]
        if _is_ahu_unit(ln):
            e = k
            while e + 1 < n and not _is_ahu_unit(rows[e + 1]) and _is_ahu_part(rows[e + 1]):
                e += 1
            groups.append([k, e, "ahu", None])
            k = e + 1
            continue
        cur = groups[-1] if groups else None
        if ln.get("category") == CONTROLLER_CATEGORY:
            groups.append([k, k, "controller", k])
        elif _is_attachment(ln) and cur is not None and cur[2] == "item":
            cur[1] = k
        else:
            key = _kind(ln)
            if cur is not None and cur[2] == "item" and cur[3] == key:
                cur[1] = k
            else:
                groups.append([k, k, "item", key])
        k += 1

    c = [(g[0], g[1]) for g in groups if g[2] == "ahu" and g[1] > g[0]]
    b: list[tuple[int, int]] = []
    i = 0
    while i < len(groups):
        start, end, kind, _ = groups[i]
        i += 1
        if kind == "ahu" and start == end:          # qo'shimchasiz ketma-ket AHU lar — bitta katakda
            while i < len(groups) and groups[i][2] == "ahu" and groups[i][0] == end + 1 and groups[i][0] == groups[i][1]:
                end = groups[i][1]
                i += 1
        b.append((start, end))
    return [x for x in b if x[1] > x[0]], c


class Styles:
    """styles.xml: mavjud uslubning nusxasini boshqa son formati bilan yaratish (kasrli summalar yashirilmasin)."""

    def __init__(self, xml: bytes):
        self.root = etree.fromstring(xml)
        self.xfs = self.root.find(f"{N}cellXfs")
        self._cache: dict[tuple[str, str], str] = {}

    def with_numfmt(self, style: str | None, numfmt_id: str) -> str | None:
        if style is None:
            return None
        key = (style, numfmt_id)
        if key not in self._cache:
            xf = etree.fromstring(etree.tostring(self.xfs[int(style)]))
            xf.set("numFmtId", numfmt_id)
            xf.set("applyNumberFormat", "1")
            self.xfs.append(xf)
            self.xfs.set("count", str(len(self.xfs)))
            self._cache[key] = str(len(self.xfs) - 1)
        return self._cache[key]

    def tobytes(self) -> bytes:
        return etree.tostring(self.root, xml_declaration=True, encoding="UTF-8", standalone=True)


DECIMAL_FMT = "4"        # #,##0.00


def _col_row(ref: str) -> tuple[str, int]:
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    return m.group(1), int(m.group(2))


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


class Sheet:
    """Bitta varaq XML i ustida oddiy amallar (qiymat, yashirish, balandlik, uslub nusxasi)."""

    def __init__(self, xml: bytes):
        self.root = etree.fromstring(xml)
        self.data = self.root.find(f"{N}sheetData")
        self.rows = {int(r.get("r")): r for r in self.data.findall(f"{N}row")}
        for f in self.root.iter(f"{N}f"):                       # shablonda formula yo'q, lekin ehtiyot uchun
            f.getparent().remove(f)

    def row(self, r: int):
        el = self.rows.get(r)
        if el is None:
            el = etree.Element(f"{N}row", r=str(r))
            after = max((k for k in self.rows if k < r), default=None)
            if after is None:
                self.data.insert(0, el)
            else:
                self.rows[after].addnext(el)
            self.rows[r] = el
        return el

    def cell(self, ref: str):
        col, r = _col_row(ref)
        row = self.row(r)
        idx = _col_index(col)
        for c in row.findall(f"{N}c"):
            ccol, _ = _col_row(c.get("r"))
            ci = _col_index(ccol)
            if ci == idx:
                return c
            if ci > idx:
                new = etree.Element(f"{N}c", r=ref)
                c.addprevious(new)
                return new
        new = etree.SubElement(row, f"{N}c", r=ref)
        return new

    def set(self, ref: str, value, style_from: str | None = None) -> None:
        c = self.cell(ref)
        if style_from:
            s = self.cell(style_from).get("s")
            if s is not None:
                c.set("s", s)
        for child in list(c):
            c.remove(child)
        c.attrib.pop("t", None)
        if value is None or value == "":
            return
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            v = etree.SubElement(c, f"{N}v")
            v.text = _num_text(value)
        else:
            c.set("t", "inlineStr")
            is_ = etree.SubElement(c, f"{N}is")
            t = etree.SubElement(is_, f"{N}t")
            t.text = str(value)
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    def formula(self, ref: str, f: str, value) -> None:
        """Formula katagi (foydalanuvchi talabi 2026-10-22: summa va jami kataklari formula bilan) — hisoblangan
        qiymat ham yoziladi, Excel ochilganda ham, data_only o'qishda ham to'g'ri son ko'rinadi."""
        self.set(ref, value)
        c = self.cell(ref)
        fe = etree.Element(f"{N}f")
        fe.text = f
        c.insert(0, fe)

    def decimals_if_needed(self, ref: str, value, styles: "Styles") -> None:
        """Butun bo'lmagan summa — 2 xonali format bilan (yaxlitlanib yashirilmasin, CLAUDE.md)."""
        if value is not None and Decimal(str(value)) != Decimal(str(value)).to_integral():
            c = self.cell(ref)
            c.set("s", styles.with_numfmt(c.get("s"), DECIMAL_FMT) or c.get("s", "0"))

    def hide(self, r: int, hidden: bool = True) -> None:
        row = self.row(r)
        if hidden:
            row.set("hidden", "1")
        else:
            row.attrib.pop("hidden", None)

    def height(self, r: int, pt: float) -> None:
        row = self.row(r)
        row.set("ht", f"{pt:g}")
        row.set("customHeight", "1")

    def merge(self, refs: list[str]) -> None:
        """Kataklarni birlashtirish (mergeCells). Shablonda element bor; bo'lmasa sheetData dan keyin yaratiladi."""
        if not refs:
            return
        mc = self.root.find(f"{N}mergeCells")
        if mc is None:
            mc = etree.Element(f"{N}mergeCells")
            self.data.addnext(mc)
        for ref in refs:
            etree.SubElement(mc, f"{N}mergeCell", ref=ref)
        mc.set("count", str(len(mc)))

    def page_break_after(self, r: int) -> None:
        """Chop etishda r-qatordan keyin yangi sahifa (rowBreaks/brk id=r). Shablonda muqovadan keyin (68) bittasi bor;
        bo'lmasa OOXML tartibida pageSetup / headerFooter dan keyin yaratiladi."""
        rb = self.root.find(f"{N}rowBreaks")
        if rb is None:
            rb = etree.Element(f"{N}rowBreaks")
            anchor = self.root.find(f"{N}headerFooter")
            (anchor if anchor is not None else self.root.find(f"{N}pageSetup")).addnext(rb)
        if any(b.get("id") == str(r) for b in rb):
            return
        etree.SubElement(rb, f"{N}brk", id=str(r), max="16383", man="1")
        rb[:] = sorted(rb, key=lambda b: int(b.get("id")))
        rb.set("count", str(len(rb)))
        rb.set("manualBreakCount", str(len(rb)))

    def tobytes(self) -> bytes:
        return etree.tostring(self.root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _num_text(value) -> str:
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(d.normalize(), "f") if d == d.to_integral() else format(d, "f")


def _excel_date(d: dt.date) -> int:
    return (d - dt.date(1899, 12, 30)).days


def _perf_text(value, unit) -> str | None:
    """Excel'dagidek: 1170m3/h, 78,5kw (vergul bilan)."""
    if value is None:
        return None
    d = Decimal(str(value)).normalize()
    s = format(d, "f").replace(".", ",")
    return f"{s}{unit or ''}"


def _row_height(description: str | None, chars: int = DESC_CHARS_PER_LINE) -> float:
    if not description:
        return MIN_ROW_HEIGHT
    lines = sum(max(1, math.ceil(len(part) / chars)) for part in description.split("\n"))
    return max(MIN_ROW_HEIGHT, round(lines * LINE_HEIGHT_PT, 1))


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name)
    return re.sub(r"\s+", " ", name).strip().rstrip(".") or "KP"


def file_name(kp_number: int, project_name: str, revision_no: int) -> str:
    """Foydalanuvchi qarori: '<KP> - <loyiha>.xlsx', revision 2+ -> ' R<n>'."""
    suffix = f" R{revision_no}" if revision_no >= 2 else ""
    return safe_filename(f"{kp_number} - {project_name.strip()}{suffix}") + ".xlsx"


def _discount_label(reason: str | None, pct: Decimal, annex_name: str, multi: bool) -> str:
    if reason and reason.strip().lower().startswith("скидка"):
        return reason.strip()                                    # eski KP: "Скидка на продукцию 10 %"
    p = format((pct * 100).quantize(Decimal("0.01")).normalize(), "f")    # to'liq aniq foiz (C006) — yozuvda 2 xona
    return f"Скидка {p} %" + (f" ({annex_name})" if multi else "")


_DRAWING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><xdr:twoCellAnchor editAs="oneCell"><xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:to><xdr:col>9</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{rows}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="KP muqova" descr="Коммерческое предложение — обложка"/><xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:twoCellAnchor></xdr:wsDr>"""
_DRAWING_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/cover.jpeg"/></Relationships>"""


def _apply_cover(files: dict[str, bytes], sh: Sheet, image: bytes) -> None:
    """1-sahifa: eski muqova (rasmlar va matnlar) o'rniga yangi muqova rasmi — B–I ustunlari × 1–68-qatorlar."""
    for col in sh.root.find(f"{N}cols"):
        w = COVER_COL_WIDTHS.get(int(col.get("min")))
        if w is not None and col.get("min") == col.get("max"):
            col.set("width", format(w, "f").rstrip("0").rstrip("."))     # to'liq aniqlik (":g" 6 xonagacha qisqartiradi)
    for r, row in sh.rows.items():
        if r < COVER_ROWS:
            for c in row.findall(f"{N}c"):
                for child in list(c):
                    c.remove(child)
                c.attrib.pop("t", None)
    for name in [n for n in files if n.startswith("xl/media/")]:
        del files[name]
    files["xl/media/cover.jpeg"] = image
    files["xl/drawings/drawing1.xml"] = _DRAWING.format(rows=COVER_ROWS).encode()
    files["xl/drawings/_rels/drawing1.xml.rels"] = _DRAWING_RELS.encode()
    # Excel saqlaganda rasmni siqmasin (standart: 220 ppi gacha kichraytiradi — muqova xiralashadi)
    wb = files["xl/workbook.xml"].decode()
    if "autoCompressPictures" not in wb:
        wb = re.sub(r"<workbookPr(\s|/)", r'<workbookPr autoCompressPictures="0"\1', wb, count=1)
    files["xl/workbook.xml"] = wb.encode()
    ct = files["[Content_Types].xml"].decode()
    if 'Extension="jpeg"' not in ct:
        ct = ct.replace('<Default Extension="png"', '<Default Extension="jpeg" ContentType="image/jpeg"/><Default Extension="png"', 1)
    files["[Content_Types].xml"] = ct.encode()
    _full_page(sh)


COVER_MARGIN_IN = "0.2"        # ~5 mm; printer o'z majburiy hoshiyasi kattaroq bo'lsa, Excel o'shanisini oladi


def _full_page(sh: Sheet) -> None:
    """Telefonda (Excel -> PDF) muqova sahifani to'liq egallasin, jadval ham shu enda (foydalanuvchi talabi 2026-10-19):
    hoshiyalar kichik, "eniga 1 sahifa" (fitToWidth=1, bo'yiga cheklovsiz), gorizontal markazda.
    Masshtab qo'lda berilmaydi: Excel PDF ni printer orqali chiqaradi, printer chegarasi va ustun enlari printerga qarab
    o'zgaradi (EPSON L15150 da chop etiladigan en 540 pt) — Excel o'zi har printerga mos masshtab tanlaydi."""
    root = sh.root
    margins = root.find(f"{N}pageMargins")
    for k in ("left", "right", "top", "bottom"):
        margins.set(k, COVER_MARGIN_IN)
    for k in ("header", "footer"):
        margins.set(k, "0")
    setup = root.find(f"{N}pageSetup")
    setup.attrib.pop("scale", None)
    setup.set("fitToWidth", "1")
    setup.set("fitToHeight", "0")
    pr = root.find(f"{N}sheetPr")
    if pr is None:
        pr = etree.Element(f"{N}sheetPr")
        root.insert(0, pr)                          # OOXML: sheetPr — birinchi element
    psp = pr.find(f"{N}pageSetUpPr")
    if psp is None:
        psp = etree.SubElement(pr, f"{N}pageSetUpPr")
    psp.set("fitToPage", "1")
    opts = root.find(f"{N}printOptions")
    if opts is None:
        opts = etree.Element(f"{N}printOptions")
        margins.addprevious(opts)                  # OOXML tartibi: printOptions -> pageMargins -> pageSetup
    opts.set("horizontalCentered", "1")


def build(conn: Connection, kp_number: int, revision_no: int | None = None,
          cover_image: bytes | None = None, vat_separate: bool = False, annex_pages: bool = False,
          line_discount_visible: bool = True) -> tuple[str, bytes]:
    """cover_image — yangi muqova (JPEG, kp_pdf.cover_jpeg); None — shablonning eski muqovasi.
    vat_separate — "NDS alohida" (foydalanuvchi talabi 2026-10-17, CLAUDE.md "Bez NDS" rejimi): narx ustunlari QQSsiz,
    Итого QQSsiz, keyin "НДС, N%" = ROUNDUP(asos × N%, 0) va sariq "Сумма с НДС", izohlardan oldin bitta bo'sh qator.
    annex_pages — "Har ilova alohida sahifada" (foydalanuvchi talabi 2026-10-22, KP 1002137): har ilova yangi sahifadan
    boshlanadi (chop etish bo'linishi); pastki qism oxirgi ilova bilan qoladi. Qiymatlarga ta'sir qilmaydi.
    line_discount_visible — mahsulot chegirmasi (0025, foydalanuvchi talabi 2026-10-22): True — jadvalda asosiy sotuv narxi,
    pastda "Скидка на отдельные позиции"; False — kataklarda darhol chegirmali narx, pastda bu qator yo'q.
    Summa (I), Итого, jami, НДС va Сумма с НДС kataklari — formula."""
    head = conn.execute(text(
        """SELECT q.kp_number, p.project_no, p.name AS project_name, e.full_name AS manager, e.phone,
                  r.id AS revision_id, r.revision_no, r.kp_date, r.display_currency AS currency
           FROM quotation q JOIN project p ON p.id = q.project_id JOIN employee e ON e.id = q.manager_id
           JOIN quotation_revision r ON r.quotation_id = q.id
           WHERE q.kp_number = :k AND (CAST(:n AS int) IS NULL OR r.revision_no = :n)
           ORDER BY r.revision_no DESC LIMIT 1"""), {"k": kp_number, "n": revision_no}).mappings().first()
    if head is None:
        raise ExportError("KP topilmadi")
    annexes = conn.execute(text("SELECT * FROM v_annex_totals WHERE revision_id = :r ORDER BY annex_no"),
                           {"r": head["revision_id"]}).mappings().all()
    lines = conn.execute(text(
        """SELECT lp.annex_id, lp.line_no, pc.name AS category, lp.description, lp.model, lp.performance,
                  lp.performance_unit, lp.quantity, lp.unit_code, lp.display_unit_price, lp.display_line_total,
                  lp.line_type, lp.unit_price_excl_vat, lp.unit_price_incl_vat, ps.name AS series,
                  lp.display_unit_net, lp.display_line_net, lp.line_discount_kind
           FROM v_line_price lp LEFT JOIN product_category pc ON pc.id = lp.category_id
           LEFT JOIN quotation_line_price_list lpl ON lpl.line_id = lp.line_id
           LEFT JOIN price_list_item pli ON pli.id = lpl.price_list_item_id
           LEFT JOIN product pr ON pr.id = pli.product_id
           LEFT JOIN product_series ps ON ps.id = pr.series_id
           WHERE lp.revision_id = :r ORDER BY lp.line_no"""), {"r": head["revision_id"]}).mappings().all()
    if not annexes:
        raise ExportError("KP da ilova yo'q")
    if len(annexes) > BLOCKS:
        raise ExportError(f"Shablonda ko'pi bilan {BLOCKS} ta ilova")
    if any(a["subtotal"] is None for a in annexes):
        raise ExportError("KP da narxi noma'lum qator bor — avval narxni kiriting (TEKSHIRISH KERAK)")
    cur = head["currency"]

    with zipfile.ZipFile(TEMPLATE) as z:
        files = {n: z.read(n) for n in z.namelist()}
    sh = Sheet(files["xl/worksheets/sheet1.xml"])
    st = Styles(files["xl/styles.xml"])

    desc_chars = DESC_CHARS_PER_LINE
    if cover_image:
        _apply_cover(files, sh, cover_image)                    # muqovadagi ma'lumot rasmda — katakchalar tozalanadi
        desc_chars = DESC_CHARS_COVER
    else:
        sh.set("H52", head["kp_number"])
        sh.set("H53", head["project_no"])
        sh.set("H54", _excel_date(head["kp_date"]))
        sh.set("B60", f"Проект - {head['project_name'].strip()}")
        sh.set("B61", f"{head['manager']} - {head['phone']}" if head["phone"] else head["manager"])

    vat_rate = conn.execute(text("SELECT vr.rate FROM quotation_revision r JOIN vat_rate vr ON vr.id = r.vat_rate_id WHERE r.id = :r"),
                            {"r": head["revision_id"]}).scalar_one()
    if vat_separate:
        lines, annexes = _excl_vat(lines, annexes, vat_rate)
    if not line_discount_visible:
        lines, annexes = _hide_line_discount(lines, annexes)
    if vat_separate:
        for b in range(min(len(annexes), BLOCKS)):              # ustun sarlavhalari
            h = BLOCK_START + BLOCK_SIZE * b + 3
            sh.set(f"H{h}", "Цена за ед. без НДС")
            sh.set(f"I{h}", "Сумма без НДС")

    multi = len(annexes) > 1
    total_before = Decimal(0)
    itogo: list[str] = []
    merges: list[str] = []
    for b in range(BLOCKS):
        s = BLOCK_START + BLOCK_SIZE * b
        if b >= len(annexes):
            for r in range(s, s + BLOCK_SIZE):
                sh.hide(r)
            continue
        a = annexes[b]
        rows = [ln for ln in lines if ln["annex_id"] == a["annex_id"]]
        if len(rows) > LINES_PER_BLOCK:
            raise ExportError(f"Ilova {a['annex_no']}: {len(rows)} qator — shablonda ko'pi bilan {LINES_PER_BLOCK} ta")
        sh.set(f"I{s}", a["annex_no"])
        sh.set(f"B{s + 1}", f"Приложение № {a['annex_no']} - {a['name']}")
        for i in range(LINES_PER_BLOCK):
            r = s + 4 + i
            if i >= len(rows):
                sh.hide(r)
                continue
            ln = rows[i]
            sh.set(f"B{r}", ln["category"])
            sh.set(f"C{r}", ln["description"])
            sh.set(f"D{r}", ln["model"])
            sh.set(f"E{r}", _perf_text(ln["performance"], ln["performance_unit"]))
            sh.set(f"F{r}", ln["quantity"])
            sh.set(f"G{r}", ln["unit_code"])
            sh.set(f"H{r}", ln["display_unit_price"])
            sh.formula(f"I{r}", f"H{r}*F{r}", ln["display_line_total"])
            sh.decimals_if_needed(f"H{r}", ln["display_unit_price"], st)
            sh.decimals_if_needed(f"I{r}", ln["display_line_total"], st)
            sh.height(r, _row_height(ln["description"], desc_chars))
        b_groups, c_groups = merge_groups(rows)
        for col, spans in (("B", b_groups), ("C", c_groups)):
            for g0, g1 in spans:
                r0, r1 = s + 4 + g0, s + 4 + g1
                merges.append(f"{col}{r0}:{col}{r1}")
                for r in range(r0 + 1, r1 + 1):
                    sh.set(f"{col}{r}", None)
        for g0, g1 in c_groups:                             # AHU tavsifi bitta katakda — guruh bo'yi unga yetsin
            each = max(MIN_ROW_HEIGHT, math.ceil(_row_height(rows[g0]["description"], desc_chars) / (g1 - g0 + 1) * 10) / 10)
            for r in range(s + 4 + g0, s + 5 + g1):
                sh.height(r, each)
        sh.set(f"B{s + 82}", f"Итого  {cur}")
        sh.formula(f"F{s + 82}", f"SUM(F{s + 4}:F{s + 81})", sum((ln["quantity"] for ln in rows), Decimal(0)))
        sh.formula(f"H{s + 82}", f"SUM(I{s + 4}:I{s + 81})", a["subtotal"])
        itogo.append(f"H{s + 82}")
        sh.decimals_if_needed(f"H{s + 82}", a["subtotal"], st)
        total_before += a["subtotal"]

    sh.merge(merges)
    for r in SPACER_ROWS:
        sh.hide(r)
    if annex_pages:                                   # 1-ilova muqovadan keyin (68) allaqachon yangi sahifada
        for b in range(1, min(len(annexes), BLOCKS)):
            sh.page_break_after(BLOCK_START + BLOCK_SIZE * b - 1)      # oldingi ilovaning "Итого" sidan keyin

    if vat_separate:
        grand = _footer_vat_separate(sh, st, annexes, total_before, cur, vat_rate, multi, itogo)
    else:
        grand = _footer_vat_included(sh, st, annexes, total_before, cur, multi, itogo)

    sh.set("B1079", "Цены указаны в национальной валюте" if cur == "UZS" else "Цены указаны в долларах США")
    for r in HIDDEN_NOTE_ROWS:
        sh.hide(r)
    sh.set("B1083", WARRANTY.format(years="1 года " if grand > 800_000_000 else "1 год "))

    files["xl/worksheets/sheet1.xml"] = sh.tobytes()
    files["xl/styles.xml"] = st.tobytes()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return file_name(head["kp_number"], head["project_name"], head["revision_no"]), out.getvalue()


def _excl_vat(lines, annexes, vat_rate: Decimal):
    """Qatorlar va ilova jamlari QQSsiz (KP valyutasida). AHU narxi — ROUNDUP (Alembic 0021 qoidasi QQSsiz uchun ham).
    Mahsulot chegirmasi bor qator: chegirmali narx QQS bilan narxdan hisoblangan (0025) — QQSsizi = u / (1 + QQS)."""
    out_lines = []
    for ln in lines:
        d = dict(ln)
        incl, disp = ln["unit_price_incl_vat"], ln["display_unit_price"]
        factor = (disp / incl) if incl else Decimal(1)                       # 1 yoki USD->UZS kurs
        unit = (ln["unit_price_excl_vat"] or Decimal(0)) * factor
        ahu = ln["line_type"] == "ahu" or ln["category"] == "AHU"
        if ahu:
            unit = Decimal(math.ceil(unit))
        net = unit
        if ln["line_discount_kind"] is not None:
            net = ln["display_unit_net"] / (1 + vat_rate)
            if ahu:
                net = Decimal(math.ceil(net))
        d["display_unit_price"], d["display_line_total"] = unit, unit * ln["quantity"]
        d["display_unit_net"], d["display_line_net"] = net, net * ln["quantity"]
        out_lines.append(d)
    out_annexes = []
    for a in annexes:
        d = dict(a)
        mine = [ln for ln in out_lines if ln["annex_id"] == a["annex_id"]]
        sub = sum((ln["display_line_total"] for ln in mine), Decimal(0))
        net = sum((ln["display_line_net"] for ln in mine), Decimal(0))
        pct = a["discount_pct"] or Decimal(0)
        d["subtotal"], d["net_subtotal"], d["line_discount_amount"] = sub, net, sub - net
        d["discount_amount"], d["total_after_discount"] = net * pct, net * (1 - pct)
        out_annexes.append(d)
    return out_lines, out_annexes


def _hide_line_discount(lines, annexes):
    """"Mahsulot chegirmasi ko'rinmasin": kataklarga darhol chegirmali narx, pastda mahsulot chegirmasi qatori yo'q
    (foydalanuvchi talabi 2026-10-22). Ilova chegirmasi (agar bo'lsa) avvalgidek pastda qoladi."""
    out_lines = []
    for ln in lines:
        d = dict(ln)
        d["display_unit_price"], d["display_line_total"] = ln["display_unit_net"], ln["display_line_net"]
        out_lines.append(d)
    out_annexes = []
    for a in annexes:
        d = dict(a)
        d["subtotal"], d["line_discount_amount"] = a["net_subtotal"], Decimal(0)
        out_annexes.append(d)
    return out_lines, out_annexes


DISCOUNT_ROW_HEIGHT = 21          # chegirma qatori ingichka (foydalanuvchi talabi 2026-10-21)
FOOTER_TOTAL_HEIGHT = 24.6        # "Общая стоимость" / "Итого со скидкой" — shablondagi 1072-qator balandligi
PLAIN_ROW = 1064                  # shablondagi chegarasiz, ranglanmagan qator — bo'sh qator uslubi shundan olinadi


def _blank_row(sh: Sheet, r: int, plain: dict) -> None:
    """Bo'limlar orasidagi bitta bo'sh qator (Итого -> Общая стоимость, oxirgi jami -> Примечание)."""
    for col, s_ in plain.items():
        c = sh.cell(f"{col}{r}")
        if s_ is None:
            c.attrib.pop("s", None)
        else:
            c.set("s", s_)
        sh.set(f"{col}{r}", None)
    sh.height(r, LINE_HEIGHT_PT)
    sh.hide(r, hidden=False)


LINE_DISCOUNT_LABEL = "Скидка на отдельные позиции"


def _discount_items(annexes, multi: bool, room: int) -> list[tuple[str, Decimal]]:
    """Avval mahsulot (qator) chegirmalari jami, keyin ilova chegirmalari (tartib — foydalanuvchi qarori 2026-10-22)."""
    line_total = sum((a.get("line_discount_amount") or Decimal(0) for a in annexes), Decimal(0))
    head = [(LINE_DISCOUNT_LABEL, line_total)] if line_total else []
    return head + _annex_discount_items(annexes, multi, room - len(head))


def _annex_discount_items(annexes, multi: bool, room: int) -> list[tuple[str, Decimal]]:
    discounts = [a for a in annexes if a["discount_pct"] is not None]
    if not discounts:
        return []
    labels = {_discount_label(a["discount_reason"], a["discount_pct"], a["name"], False) for a in discounts}
    if multi and len(discounts) == len(annexes) and len({a["discount_pct"] for a in discounts}) == 1 and len(labels) == 1:
        # hamma ilovaga bir xil chegirma — bitta qator, summasi jami (foydalanuvchi talabi 2026-10-21).
        # Ichki izoh (masalan "kimning ruxsati bilan") KP da ko'rinmaydi — solishtirishda faqat ko'rinadigan yozuv.
        return [(labels.pop(), sum((a["discount_amount"] for a in discounts), Decimal(0)))]
    if len(discounts) > room:                                     # juda ko'p — bitta umumiy qatorga
        return [("Скидка (ilovalar bo'yicha)", sum((a["discount_amount"] for a in discounts), Decimal(0)))]
    return [(_discount_label(a["discount_reason"], a["discount_pct"], a["name"], multi), a["discount_amount"]) for a in discounts]


def _footer_vat_separate(sh: Sheet, st: Styles, annexes, total_before: Decimal, cur: str, vat_rate: Decimal, multi: bool,
                         itogo: list[str]) -> Decimal:
    """[Общая стоимость] [Скидка… / Итого со скидкой] → "НДС, N%" (1073) → sariq "Сумма с НДС" (1074) → bo'sh qator (1075).
    Jami, НДС va Сумма с НДС kataklari — formula (chegirma qatorlari — son)."""
    style = {k: {col: sh.cell(f"{col}{r}").get("s") for col in "ABCDEFGHI"}
             for k, r in (("total", FOOTER_TOTAL), ("vat", 1073), ("sum", 1074), ("discount", 1074))}
    plain = {col: sh.cell(f"{col}{PLAIN_ROW}").get("s") for col in "ABCDEFGHI"}
    for r in (*SPACER_ROWS, FOOTER_TOTAL, *FOOTER_FREE):
        for col in "BCDEF":
            sh.set(f"{col}{r}", None)
        sh.hide(r)
    items: list[tuple[str, Decimal, str]] = []
    if multi:
        items.append((f"Общая стоимость   {cur}", total_before, "total"))
    disc = _discount_items(annexes, multi, room=len(SPACER_ROWS) - 2)
    base = total_before
    if disc:
        items += [(label, -amount, "discount") for label, amount in disc]
        base = sum((a["total_after_discount"] for a in annexes), Decimal(0))
        items.append((f"Итого со скидкой, {cur}", base, "total"))
    vat = Decimal(math.ceil(base * vat_rate))                     # ROUNDUP(asos × 12%, 0)
    pct = format((vat_rate * 100).normalize(), "f")
    items += [(f"НДС, {pct}%", vat, "vat"), ("Сумма с НДС", base + vat, "sum")]
    first = 1074 - len(items) + 1                                  # "Сумма с НДС" doim 1074 da, НДС 1073 da
    rows_of = dict(zip(range(len(items)), range(first, 1075)))
    disc_rows = [rows_of[i] for i, it in enumerate(items) if it[2] == "discount"]
    grand_ref = f"F{first}" if multi else itogo[0]
    base_ref = "F1072" if disc else grand_ref                  # "Итого со скидкой" doim НДС dan oldingi qatorda
    for i, ((label, amount, kind), r) in enumerate(zip(items, range(first, 1075))):
        for col, s_ in style[kind].items():
            if s_ is not None:
                sh.cell(f"{col}{r}").set("s", s_)
        sh.set(f"B{r}", label)
        if kind == "discount":
            sh.set(f"F{r}", amount)
        elif kind == "vat":
            sh.formula(f"F{r}", f"ROUNDUP({base_ref}*{pct}/100,0)", amount)
        elif kind == "sum":
            sh.formula(f"F{r}", f"{base_ref}+F1073", amount)
        elif multi and i == 0:                                     # Общая стоимость
            sh.formula(f"F{r}", "+".join(itogo), amount)
        else:                                                      # Итого со скидкой
            sh.formula(f"F{r}", f"{grand_ref}+SUM(F{disc_rows[0]}:F{disc_rows[-1]})", amount)
        sh.decimals_if_needed(f"F{r}", amount, st)
        if kind == "discount":
            sh.height(r, DISCOUNT_ROW_HEIGHT)
        sh.hide(r, hidden=False)
    _blank_row(sh, first - 1, plain)                               # Итого (oxirgi ilova) bilan orada bitta bo'sh qator
    sh.hide(1075, hidden=False)                                    # izohlar (Примечание) bilan orada bitta bo'sh qator
    return base + vat


def _footer_vat_included(sh: Sheet, st: Styles, annexes, total_before: Decimal, cur: str, multi: bool,
                         itogo: list[str]) -> Decimal:
    """Итого (oxirgi ilova) -> bo'sh qator -> [Общая стоимость] [Скидка… / Итого со скидкой] -> bo'sh qator -> Примечание.
    Pastki qism bo'sh bo'lsa — Итого va Примечание orasida bitta bo'sh qator (foydalanuvchi talabi 2026-10-21)."""
    plain = {col: sh.cell(f"{col}{PLAIN_ROW}").get("s") for col in "ABCDEFGHI"}
    styles_discount = {col: sh.cell(f"{col}1074").get("s") for col in "ABCDEFGHI"}
    styles_total = {col: sh.cell(f"{col}{FOOTER_TOTAL}").get("s") for col in "ABCDEFGHI"}
    _blank_row(sh, SPACER_ROWS[-1], plain)                  # Итого dan keyingi bo'sh qator

    # Общая стоимость — faqat 2+ ilova (CLAUDE.md)
    sh.set(f"B{FOOTER_TOTAL}", f"Общая стоимость   {cur}")
    sh.formula(f"F{FOOTER_TOTAL}", "+".join(itogo), total_before)
    sh.decimals_if_needed(f"F{FOOTER_TOTAL}", total_before, st)
    sh.hide(FOOTER_TOTAL, hidden=not multi)

    free = list(FOOTER_FREE)
    for r in free:
        for col in "BCDEF":
            sh.set(f"{col}{r}", None)
        sh.hide(r)
    # Chegirmalar: bir xil bo'lsa bitta qator, aks holda har ilova alohida; keyin "Итого со скидкой".
    # Kamida bitta qator Примечание oldidagi bo'sh qator uchun qoladi.
    items = _discount_items(annexes, multi, room=len(free) - 2)
    after = total_before
    k = 0
    for label, amount in items:
        r = free[k]
        k += 1
        for col, s in styles_discount.items():              # butun qator — sariq (1074 kabi)
            if s is not None:
                sh.cell(f"{col}{r}").set("s", s)
        sh.set(f"B{r}", label)
        sh.set(f"F{r}", -amount)
        sh.decimals_if_needed(f"F{r}", amount, st)
        sh.height(r, DISCOUNT_ROW_HEIGHT)
        sh.hide(r, hidden=False)
    if items:
        r = free[k]
        k += 1
        after = sum((a["total_after_discount"] for a in annexes), Decimal(0))
        for col, s in styles_total.items():                # "Общая стоимость" qatori uslubida
            if s is not None:
                sh.cell(f"{col}{r}").set("s", s)
        sh.set(f"B{r}", f"Итого со скидкой, {cur}")
        sh.formula(f"F{r}", f"F{FOOTER_TOTAL}+SUM(F{free[0]}:F{free[k - 2]})", after)
        sh.decimals_if_needed(f"F{r}", after, st)
        sh.height(r, FOOTER_TOTAL_HEIGHT)
        sh.hide(r, hidden=False)
    if multi or items:
        _blank_row(sh, free[k], plain)                      # Примечание dan oldingi bo'sh qator
    return after
