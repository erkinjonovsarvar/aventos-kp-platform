# AVENTOS KP — muqova shablonlari

Ikki muqova: **KP_cover_VRF_5S** (Hisense Hi-FLEXI 5S) va **KP_cover_AHU** (AVENTOS AHU).
Har biri A4 (210 × 297 mm), 1 sahifa.

## Fayllar
- `KP_cover_*.html` — tahrirlanadigan manba (Cowork / Claude Code shu faylni o'zgartiradi).
- `KP_cover_*.pdf` — tayyor PDF namunasi.
- `assets/` — fon rasmlari va AVENTOS logotipi (rangli va oq).
- `fonts/` — Montserrat (400–800). Internetsiz ishlaydi, PDF'ga to'liq joylanadi.

## Har bir KP uchun almashtiriladigan joylar (HTML ichida matn sifatida)
| Joy | Hozirgi qiymat |
|---|---|
| Proyekt nomi | `Укажите название проекта` |
| KP raqami | `№ 1002001` |
| Proyekt raqami | `1657` |
| Sana | `17.10.2026` |
| Menejer ismi | `Имя Фамилия` |
| Menejer telefoni | `+998 __ ___ __ __` |
| Shourum manzili | `г. Ташкент, [адрес шоурума]` |

## PDF sifatini saqlash qoidalari
1. PDF'ni faqat Chromium / Chrome orqali chiqaring (Playwright `page.pdf`):
   `width: 210mm, height: 297mm, printBackground: true, margin: 0, preferCSSPageSize: true`.
2. Viewport 794 × 1123 px — sahifa aynan shu o'lchamda chizilgan, o'zgartirmang.
3. HTML'ni PDF'ga aylantirishdan oldin `document.fonts.ready` ni kuting — aks holda shrift almashib qoladi.
4. Matnlar PDF'da vektor holatda qoladi (kattalashtirganda xiralashmaydi). Rasmni skrinshot qilib qo'ymang.
5. Uzun proyekt nomi 1 qatorga sig'masa, shrift o'lchamini 19px dan 16–17px ga tushiring, qatorni sindirmang.
6. Muqovadan keyingi sahifalar (spetsifikatsiya, narx jadvali) alohida HTML/PDF bo'lib, oxirida birlashtiriladi — muqova faylining o'zini o'zgartirmang.
