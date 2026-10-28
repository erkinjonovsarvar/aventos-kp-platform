"""Muqova fonlaridan rasmga "yopishtirilgan" yozuv va belgilarni olib tashlash (foydalanuvchi: sifati past, 2026-10-17).

Fon JPEG (1810 px) ichidagi yozuvlar kattalashtirilganda xira. Bu skript ularni atrofdagi fon bilan to'ldiradi va
*_clean.jpg saqlaydi; yozuvlar kp_pdf.fill_cover da Montserrat / SVG / logotip PNG bilan tiniq qayta chiziladi.
Asl fayllar o'zgarmaydi. Hisense logotiplari (asl fayli yo'q) fonda qoladi.

  AHU va VRF: "НАДЕЖНЫЙ ПАРТНЕР / В СФЕРЕ КЛИМАТИЧЕСКИХ РЕШЕНИЙ" (to'q yashil tasma ustida).
  VRF qo'shimcha: AVENTOS logotipi va "|" ajratgich, teal chiziqcha, "ПРОФЕССИОНАЛЬНЫЕ РЕШЕНИЯ…", "КОММЕРЧЕСКОЕ /
  ПРЕДЛОЖЕНИЕ", "на поставку климатического / оборудования Hisense", 4 ta ikonka va ularning yozuvlari (osmon ustida),
  pastdagi oq AVENTOS logotipi (to'q tasmada).

Ishga tushirish (natija repoda):  .venv\\Scripts\\python.exe -I backend\\app\\kp_cover\\clean_backgrounds.py
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ASSETS = Path(__file__).parent / "assets"
TAGLINE_BOX = (120, 1728, 798, 1808)           # (x0, y0, x1, y1) 1810x2560 fonda; yozuv 135..783 × 1738..1798
VRF_FOOTER_LOGO_BOX = (76, 2378, 496, 2472)     # VRF: pastdagi oq AVENTOS logotipi (89..482 × 2389..2460), to'q tasmada
VRF_SKY_BOXES = [                               # osmon ustidagi elementlar (VRF bloki va Hisense logotipiga tegmaydi)
    (100, 112, 1012, 272),                      # AVENTOS logotipi + "|" ajratgich
    (118, 350, 700, 496),                       # teal chiziqcha + "ПРОФЕССИОНАЛЬНЫЕ РЕШЕНИЯ / ДЛЯ КОМФОРТНОГО БУДУЩЕГО"
    (122, 542, 1000, 784),                      # "КОММЕРЧЕСКОЕ / ПРЕДЛОЖЕНИЕ"
    (124, 800, 776, 912),                       # "на поставку климатического / оборудования Hisense"
    (88, 950, 870, 1176),                       # ikonkalar va yozuvlari
]


def _box(x: np.ndarray, r: int, axis: int) -> np.ndarray:
    """1 o'qli box-blur (cumsum), chetlar takrorlanadi."""
    xp = np.pad(x, [(r + 1, r) if i == axis else (0, 0) for i in range(x.ndim)], mode="edge")
    c = np.cumsum(xp, axis=axis)
    hi = np.take(c, range(2 * r + 1, c.shape[axis]), axis=axis)
    lo = np.take(c, range(0, c.shape[axis] - 2 * r - 1), axis=axis)
    return (hi - lo) / (2 * r + 1)


def _blur(x: np.ndarray, r: float) -> np.ndarray:
    """Gaussga yaqin xiralash: 3 marta box-blur (2 o'qda)."""
    k = max(1, int(r / 1.7))
    for _ in range(3):
        x = _box(_box(x, k, 0), k, 1)
    return x


def _fill(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Niqobdagi piksellarni atrofdagi fon bilan to'ldirish (normallashtirilgan konvolyutsiya, kichikdan kattaga)."""
    out = rgb.copy()
    known = (~mask).astype(np.float64)
    todo = mask.copy()
    for r in (10, 24, 56, 120):
        w = _blur(known, r)
        ok = todo & (w > 0.02)
        for ch in range(3):
            v = _blur(out[:, :, ch] * known, r) / np.maximum(w, 1e-9)
            out[:, :, ch] = np.where(ok, v, out[:, :, ch])
        todo &= ~ok
        if not todo.any():
            break
    return out


def _clean_tagline(img: Image.Image, box_: tuple[int, int, int, int] = TAGLINE_BOX) -> None:
    """To'q yashil tasmadagi och yozuv/logotip: median fon bahosi (gradient saqlanadi)."""
    x0, y0, x1, y1 = box_
    pad = 36
    box = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    region = img.crop(box)
    bg = region.filter(ImageFilter.MedianFilter(31)).filter(ImageFilter.MedianFilter(31)).filter(ImageFilter.GaussianBlur(3))
    r, b = np.asarray(region).astype(np.int16), np.asarray(bg).astype(np.int16)
    diff = np.abs(r - b).max(axis=2)
    mask = np.zeros(diff.shape, bool)
    mask[pad:pad + (y1 - y0), pad:pad + (x1 - x0)] = diff[pad:pad + (y1 - y0), pad:pad + (x1 - x0)] > 6
    m = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(2))
    alpha = np.asarray(m).astype(np.float64)[:, :, None] / 255.0
    img.paste(Image.fromarray(np.clip(r * (1 - alpha) + b * alpha, 0, 255).astype(np.uint8)), box[:2])


def _clean_sky(img: Image.Image, boxes: list[tuple[int, int, int, int]]) -> None:
    """Och osmon ustidagi to'q/teal yozuv va belgilar: rang bo'yicha niqob, keng to'ldirish."""
    pad = 80
    xs0, ys0 = min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad
    xs1, ys1 = max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad
    region = np.asarray(img.crop((xs0, ys0, xs1, ys1))).astype(np.float64)
    lum = region.mean(axis=2)
    ink = (lum < 205) | ((region[:, :, 1] - region[:, :, 0]) > 35)       # to'q matn, teal belgilar va ularning qirrasi
    inside = np.zeros(lum.shape, bool)
    for x0, y0, x1, y1 in boxes:
        inside[y0 - ys0:y1 - ys0, x0 - xs0:x1 - xs0] = True
    mask = ink & inside
    mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(11))) > 0
    mask &= inside
    filled = _fill(region, mask)
    soft = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))).astype(np.float64)[:, :, None] / 255
    soft = np.where(mask[:, :, None], 1.0, soft) * inside[:, :, None]
    out = region * (1 - soft) + filled * soft
    img.paste(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)), (xs0, ys0))


def _clean_light_on_dark(img: Image.Image, box_: tuple[int, int, int, int]) -> None:
    """To'q tasmadagi katta och logotip: yorqin piksellar niqobi, atrofdagi to'q fondan to'ldirish."""
    pad = 60
    x0, y0, x1, y1 = box_
    region = np.asarray(img.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad))).astype(np.float64)
    lum = region.mean(axis=2)
    inside = np.zeros(lum.shape, bool)
    inside[pad:pad + (y1 - y0), pad:pad + (x1 - x0)] = True
    mask = (lum > np.median(lum) + 14) & inside
    mask = (np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))) > 0) & inside
    filled = _fill(region, mask)
    soft = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))).astype(np.float64)[:, :, None] / 255
    soft = np.where(mask[:, :, None], 1.0, soft) * inside[:, :, None]
    img.paste(Image.fromarray(np.clip(region * (1 - soft) + filled * soft, 0, 255).astype(np.uint8)), (x0 - pad, y0 - pad))


def clean(src: Path, dst: Path, sky_boxes: list | None = None) -> None:
    img = Image.open(src).convert("RGB")
    _clean_tagline(img)
    if sky_boxes:
        _clean_sky(img, sky_boxes)
        _clean_light_on_dark(img, VRF_FOOTER_LOGO_BOX)
    img.save(dst, "JPEG", quality=98, subsampling=0, optimize=True)


if __name__ == "__main__":
    clean(ASSETS / "cover_ahu_bg.jpg", ASSETS / "cover_ahu_bg_clean.jpg")
    clean(ASSETS / "cover_vrf_5s_bg.jpg", ASSETS / "cover_vrf_5s_bg_clean.jpg", VRF_SKY_BOXES)
    print("tayyor: cover_ahu_bg_clean.jpg, cover_vrf_5s_bg_clean.jpg")
