"""KP ni PDF'ga chiqarish: 1-sahifa — muqova (kp_cover/*.html), keyingilari — Excel shablonining aynan nusxasi.

Foydalanuvchi qarorlari (2026-10-17):
- Muqova: AVENTOS (AHU) — KP da faqat AHU va aksessuarlar (valve), Hisense yo'q; Hisense VRF 5S — faqat VRF tizimi.
  Boshqa holatda (chiller, fankoil, AHU+VRF aralash) avtomatik tanlanmaydi — foydalanuvchi tanlaydi.
- Narx sahifalari — Excel eksportining asl nusxasi (kp_export.build -> Excel -> PDF).
- Shourum: г. Ташкент, улица Эльбек 146; email: info@aventosgroup.uz; menejer va telefoni — bazadan.

Muqova kp_cover/README.md qoidalari bilan chiqariladi: Chromium (Microsoft Edge, headless), A4, fon bilan, chegarasiz,
794×1123 px, shriftlar yuklanishi kutiladi, matn vektor. Muqova fayllarining o'zi o'zgartirilmaydi — vaqtinchalik nusxa to'ldiriladi.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import kp_export
from .config import settings

COVER_DIR = Path(__file__).parent / "kp_cover"
COVERS = {"ahu": "KP_cover_AHU.html", "vrf": "KP_cover_VRF_5S.html"}
SHOWROOM = "г. Ташкент, улица Эльбек 146"
EMAIL = "info@aventosgroup.uz"

AHU_CATEGORIES = {"AHU", "Аксесуары"}                                   # AVENTOS: AHU + valve, Hisense yo'q
VRF_CATEGORIES = {"VRF", "Панель вб VRF", "Контроллер", "Рефнет"}      # faqat Hisense VRF tizimi

_excel_lock = threading.Lock()          # Excel COM — bir vaqtda bitta


class PdfError(Exception):
    pass


# ------------------------------------------------------------------ muqova tanlash
def auto_cover(categories: set[str | None]) -> str | None:
    """'ahu' | 'vrf' | None (aniq emas — foydalanuvchi tanlaydi)."""
    cats = {c for c in categories}
    if not cats or None in cats:
        return None
    if "AHU" in cats and cats <= AHU_CATEGORIES:
        return "ahu"
    if "VRF" in cats and cats <= VRF_CATEGORIES:
        return "vrf"
    return None


def head(conn: Connection, kp_number: int, revision_no: int | None) -> dict:
    h = conn.execute(text(
        """SELECT q.kp_number, p.project_no, p.name AS project_name, e.full_name AS manager, e.phone,
                  r.id AS revision_id, r.revision_no, r.kp_date
           FROM quotation q JOIN project p ON p.id = q.project_id JOIN employee e ON e.id = q.manager_id
           JOIN quotation_revision r ON r.quotation_id = q.id
           WHERE q.kp_number = :k AND (CAST(:n AS int) IS NULL OR r.revision_no = :n)
           ORDER BY r.revision_no DESC LIMIT 1"""), {"k": kp_number, "n": revision_no}).mappings().first()
    if h is None:
        raise PdfError("KP topilmadi")
    cats = {r[0] for r in conn.execute(text(
        """SELECT DISTINCT pc.name FROM v_line_price lp LEFT JOIN product_category pc ON pc.id = lp.category_id
           WHERE lp.revision_id = :r"""), {"r": h["revision_id"]})}
    return {**h, "auto_cover": auto_cover(cats), "categories": sorted(c or "—" for c in cats)}


# ------------------------------------------------------------------ muqovani to'ldirish
def _phone(p: str | None) -> str:
    """'(+998) 93 366 02 00' -> '+998 93 366 02 00' (muqova formati)."""
    return re.sub(r"^\((\+\d+)\)\s*", r"\1 ", p.strip()) if p else "+998 __ ___ __ __"


# Fon rasmidagi xira yozuv o'rniga tiniq matn. O'lchovlar 1810 px fondan (x 135..509 / 135..783, bosh harf tepasi
# y 1742 / 1782, bosh harf bo'yi 15 px -> Montserrat 9,4 px) × 794/1810; harflar orasi skriptda aynan shu enga moslanadi.
_TAGLINE = """<div aria-hidden="true" style="position: absolute; left: 59.2px; top: 0; font-family: 'Montserrat', sans-serif; \
font-weight: 500; font-size: 9.4px; line-height: 1; color: #DCEAEC; white-space: nowrap">\
<div class="kp-fit" data-w="164.5" style="position: absolute; top: 762.6px">НАДЕЖНЫЙ ПАРТНЕР</div>\
<div class="kp-fit" data-w="284.7" style="position: absolute; top: 780.2px">В СФЕРЕ КЛИМАТИЧЕСКИХ РЕШЕНИЙ</div></div>"""

# VRF muqovasi: fon rasmiga yopishtirilgan (xira) elementlar o'rniga tiniq HTML/SVG (clean_backgrounds.VRF_SKY_BOXES).
# O'lchov/rang — 1810 px fondan × 794/1810. Asl shrift Montserrat'dan ~19% tor: sarlavhalar asl bo'yida, eni 0,82.
_ICON = ('<div style="position: absolute; left: {x}px; top: 422.7px; width: 45.6px; height: 45.6px; box-sizing: border-box; '
         'border-radius: 50%; border: 2px solid #36948F; background: #FDFDFD; display: flex; align-items: center; '
         'justify-content: center"><svg aria-hidden="true" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#1D9A93" '
         'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{svg}</svg></div>'
         '<div style="position: absolute; left: {lx}px; top: 473.6px; width: 110px; text-align: center; font-size: 9.6px; '
         'line-height: 14px; font-weight: 500; color: #51666F">{label}</div>')
_ICONS = [
    (82.7, '<path d="M12 21c-4-3-6-7-6-11 0-3 2.5-6 6-8 3.5 2 6 5 6 8 0 4-2 8-6 11z"></path><path d="M12 21V9"></path>',
     "Энерго-<br>эффективность"),
    (167.4, '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"></path><path d="M9 12l2 2 4-4"></path>',
     "Надежность<br>и качество"),
    (252.5, '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38'
            'a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73'
            'l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25'
            'a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74'
            'l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z">'
            '</path><circle cx="12" cy="12" r="3"></circle>',
     "Инновационные<br>технологии"),
    (338.4, '<path d="m10 20-1.25-2.5L6 18"></path><path d="M10 4 8.75 6.5 6 6"></path><path d="m14 20 1.25-2.5L18 18"></path>'
            '<path d="m14 4 1.25 2.5L18 6"></path><path d="m17 21-3-6h-4"></path><path d="m17 3-3 6 1.5 3"></path>'
            '<path d="M2 12h6.5L10 9"></path><path d="m20 10-1.5 2 1.5 2"></path><path d="M22 12h-6.5L14 15"></path>'
            '<path d="m4 10 1.5 2L4 14"></path><path d="m7 21 3-6-1.5-3"></path><path d="m7 3 3 6h4"></path>',
     "Комфорт<br>в любое время<br>года"),
]
_VRF_OVERLAY = (
    '<div aria-hidden="true" style="position: absolute; left: 0; top: 0; width: 794px; height: 600px; '
    "font-family: 'Montserrat', sans-serif\">"
    '<img src="assets/aventos_logo.png" alt="" style="position: absolute; left: 59.2px; top: 54.4px; width: 343.9px; height: auto">'
    '<div style="position: absolute; left: 437.4px; top: 56.2px; width: 1.8px; height: 57px; background: #4B6774"></div>'
    '<div style="position: absolute; left: 58.8px; top: 158.4px; width: 42px; height: 3px; border-radius: 2px; background: #1D9A93"></div>'
    '<div class="kp-fit" data-w="231.6" style="position: absolute; left: 60.5px; top: 183.2px; font-size: 11.9px; line-height: 1; '
    'font-weight: 500; color: #3B4F5E; white-space: nowrap">ПРОФЕССИОНАЛЬНЫЕ РЕШЕНИЯ</div>'
    '<div class="kp-fit" data-w="223.7" style="position: absolute; left: 59.2px; top: 200.3px; font-size: 11.9px; line-height: 1; '
    'font-weight: 500; color: #3B4F5E; white-space: nowrap">ДЛЯ КОМФОРТНОГО БУДУЩЕГО</div>'
    '<div class="kp-fit" data-w="371.1" data-k="0.82" style="position: absolute; left: 61.4px; top: 236.95px; font-size: 49.5px; '
    'line-height: 1; font-weight: 800; color: #082131; white-space: nowrap">КОММЕРЧЕСКОЕ</div>'
    '<div class="kp-fit" data-w="368.9" data-k="0.82" style="position: absolute; left: 61px; top: 284.35px; font-size: 49.5px; '
    'line-height: 1; font-weight: 800; color: #029591; white-space: nowrap">ПРЕДЛОЖЕНИЕ</div>'
    '<div class="kp-fit" data-w="270.7" data-k="0.82" style="position: absolute; left: 61.9px; top: 349.1px; font-size: 22px; '
    'line-height: 1; font-weight: 500; color: #203546; white-space: nowrap">на поставку климатического</div>'
    '<div class="kp-fit" data-w="221.5" data-k="0.82" style="position: absolute; left: 61.4px; top: 373.7px; font-size: 22px; '
    'line-height: 1; font-weight: 500; color: #203546; white-space: nowrap">оборудования <b style="font-weight: 800; '
    'color: #0A8D88">Hisense</b></div>'
    + "".join(_ICON.format(x=round(cx - 22.8, 2), lx=round(cx - 55, 2), svg=svg, label=label) for cx, svg, label in _ICONS)
    + "</div>"
    + '<img src="assets/aventos_logo_white.png" alt="" aria-hidden="true" style="position: absolute; left: 39px; '
      'top: 1050.4px; width: 172.4px; height: auto">'                    # pastdagi oq logotip (89..482 × 2389..2460)
)

# Uzun loyiha nomi: 19px -> 17 -> 16px (bir qatorda); 16px da ham sig'masa — 2 qatorga (README 5-qoida)
_FIT_SCRIPT = """<script>
document.fonts.ready.then(function () {
  // .kp-fit: asl fondagi en (data-w) ga aniq moslash — gorizontal masshtab (data-k) + harf orasi
  document.querySelectorAll('.kp-fit').forEach(function (t) {
    var k = parseFloat(t.dataset.k || '1'), n = t.textContent.length;
    t.style.transformOrigin = '0 0';
    if (k !== 1) t.style.transform = 'scaleX(' + k + ')';
    var w = t.getBoundingClientRect().width;
    t.style.letterSpacing = ((parseFloat(t.dataset.w) - w) / ((n - 1) * k)) + 'px';
  });
  var el = document.getElementById('kp-project');
  el.style.whiteSpace = 'nowrap';
  [19, 17, 16].some(function (px) { el.style.fontSize = px + 'px'; return el.scrollWidth <= el.clientWidth; });
  if (el.scrollWidth > el.clientWidth) el.style.whiteSpace = 'normal';
  document.body.setAttribute('data-ready', '1');
});
</script>"""


def fill_cover(kind: str, h: dict) -> str:
    src = (COVER_DIR / COVERS[kind]).read_text(encoding="utf-8")
    kp = f"№ {h['kp_number']}" + (f" R{h['revision_no']}" if h["revision_no"] > 1 else "")
    date = h["kp_date"].strftime("%d.%m.%Y")
    e = lambda s: html.escape(str(s), quote=True)                       # noqa: E731 — foydalanuvchi matni HTML sifatida emas
    repl = [
        ('<div style="font-size: 19px; line-height: 1.25; font-weight: 800; color: #12303A">Укажите название проекта</div>',
         f'<div id="kp-project" style="font-size: 19px; line-height: 1.25; font-weight: 800; color: #12303A; width: 480px; '
         f'overflow: hidden">{e(h["project_name"])}</div>'),
        (">№ 1002001<", f">{e(kp)}<"),
        (">1657<", f">{e(h['project_no'])}<"),
        (">17.10.2026<", f">{e(date)}<"),
        ("<b style=\"font-weight: 700\">Имя Фамилия</b>", f"<b style=\"font-weight: 700\">{e(h['manager'])}</b>"),
        (">+998 __ ___ __ __<", f">{e(_phone(h['phone']))}<"),
        ("г. Ташкент, [адрес шоурума]", e(SHOWROOM)),
        (">info@aventos.uz<", f">{e(EMAIL)}<"),
    ]
    for a, b in repl:
        if src.count(a) != 1:
            raise PdfError(f"Muqova shablonida joy topilmadi: {a[:40]}")
        src = src.replace(a, b)
    # Fonga yopishtirilgan mayda yozuv (xira) o'rniga: tozalangan fon + Montserrat'da tiniq matn (2026-10-17)
    bg = {"ahu": "cover_ahu_bg", "vrf": "cover_vrf_5s_bg"}[kind]
    img_tag = f'<img src="assets/{bg}.jpg"'
    if src.count(img_tag) != 1:
        raise PdfError("Muqova fon rasmi topilmadi")
    end = src.index(">", src.index(img_tag)) + 1                     # fon rasmidan keyin, uning ustiga
    src = src[:end] + "\n" + _TAGLINE + (_VRF_OVERLAY if kind == "vrf" else "") + src[end:]
    src = src.replace(img_tag, f'<img src="assets/{bg}_clean.jpg"')
    return src.replace("</body>", _FIT_SCRIPT + "\n</body>")


def _edge() -> str:
    exe = settings().edge_path
    if not Path(exe).is_file():
        raise PdfError("Microsoft Edge topilmadi — PDF muqova yaratib bo'lmaydi")
    return exe


def _as_system() -> bool:
    """Server Windows fon vazifasi sifatida tizim (SYSTEM) nomidan ishlayaptimi (install_autostart.ps1, 2026-10-21)."""
    import os
    return os.name == "nt" and os.environ.get("USERNAME", "").upper().endswith("$")


def _render(kind: str, h: dict, args: list[str], out_name: str) -> bytes:
    """Muqovani vaqtinchalik nusxada to'ldirib, Edge (headless Chromium) bilan chizish.
    SYSTEM nomidan Chromium sandbox ishlamaydi (Edge kodi 1002) — shunda --no-sandbox: chiziladigan sahifa faqat
    o'zimiz yasagan lokal muqova fayli (internet sahifasi emas)."""
    with tempfile.TemporaryDirectory(prefix="kp_cover_") as tmp:
        t = Path(tmp)
        shutil.copytree(COVER_DIR / "assets", t / "assets")
        shutil.copytree(COVER_DIR / "fonts", t / "fonts")
        page = t / "cover.html"
        page.write_text(fill_cover(kind, h), encoding="utf-8")
        out = t / out_name
        cmd = [_edge(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--disable-extensions", "--hide-scrollbars", f"--user-data-dir={t / 'profile'}", "--window-size=794,1123",
               "--virtual-time-budget=8000", *(["--no-sandbox"] if _as_system() else []),
               *[a.format(out=out) for a in args], page.as_uri()]
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        if not out.is_file() or out.stat().st_size < 1000:
            raise PdfError(f"Muqova yaratilmadi (Edge kodi {r.returncode})")
        return out.read_bytes()


def cover_pdf(kind: str, h: dict) -> bytes:
    return _render(kind, h, ["--no-pdf-header-footer", "--print-to-pdf={out}"], "cover.pdf")


COVER_IMAGE_SCALE = 4          # 794x1123 -> 3176x4492 px: chop etilganda ~530 dpi (foydalanuvchi: "eng yuqori sifat", 2026-10-17)


def cover_jpeg(kind: str, h: dict) -> bytes:
    """Excel uchun muqova rasmi (JPEG, yuqori sifat) — Excel'da 1-sahifaga joylanadi (kp_export.build cover_image)."""
    import io

    from PIL import Image

    png = _render(kind, h, [f"--force-device-scale-factor={COVER_IMAGE_SCALE}", "--screenshot={out}"], "cover.png")
    img = Image.open(io.BytesIO(png)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=100, optimize=True, subsampling=0)      # eng yuqori sifat, rang siqilishisiz (4:4:4)
    return buf.getvalue()


def resolve_cover(h: dict, cover: str) -> str | None:
    kind = h["auto_cover"] if cover == "auto" else (None if cover == "none" else cover)
    if kind not in (None, *COVERS):
        raise PdfError("Muqova turi noto'g'ri")
    return kind


# ------------------------------------------------------------------ narx sahifalari: Excel -> PDF
def xlsx_to_pdf(data: bytes) -> bytes:
    import pythoncom
    import win32com.client

    with _excel_lock, tempfile.TemporaryDirectory(prefix="kp_xlsx_") as tmp:
        src, out = Path(tmp) / "kp.xlsx", Path(tmp) / "kp.pdf"
        src.write_bytes(data)
        pythoncom.CoInitialize()
        excel = wb = None
        try:
            excel = win32com.client.DispatchEx("Excel.Application")        # alohida nusxa — foydalanuvchi Excel'iga tegmaydi
            excel.Visible = False
            excel.DisplayAlerts = False
            excel.AskToUpdateLinks = False
            wb = excel.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True)
            wb.ExportAsFixedFormat(0, str(out), 0, True, False)              # xlTypePDF, sifat: standart, chop sozlamalari bilan
        except Exception as e:                                               # noqa: BLE001
            raise PdfError(f"Excel PDF ga aylantira olmadi: {e.__class__.__name__}") from None
        finally:
            if wb is not None:
                wb.Close(False)
            if excel is not None:
                excel.Quit()
            pythoncom.CoUninitialize()
        return out.read_bytes()


def merge(parts: list[tuple[bytes, int]]) -> bytes:
    """parts: (PDF, nechta boshlang'ich sahifa tashlanadi)."""
    import io

    import pypdfium2 as pdfium

    dst = pdfium.PdfDocument.new()
    for p, skip in parts:
        src = pdfium.PdfDocument(p)
        pages = list(range(skip, len(src)))
        if pages:
            dst.import_pages(src, pages)
    buf = io.BytesIO()
    dst.save(buf)
    return buf.getvalue()


def build(conn: Connection, kp_number: int, revision_no: int | None, cover: str = "auto") -> tuple[str, bytes, str | None]:
    """(fayl nomi, PDF, ishlatilgan muqova). cover: auto | ahu | vrf | none."""
    h = head(conn, kp_number, revision_no)
    kind = resolve_cover(h, cover)
    name, xlsx = kp_export.build(conn, kp_number, revision_no)
    # Yangi muqova bo'lsa Excel shablonining eski muqova sahifasi (1-sahifa) tashlanadi — ikki muqova bo'lmasin
    parts = ([(cover_pdf(kind, h), 0)] if kind else []) + [(xlsx_to_pdf(xlsx), 1 if kind else 0)]
    return name.rsplit(".", 1)[0] + ".pdf", merge(parts), kind
