# AVENTOS KP Platform

A web platform for preparing **commercial offers (KP)** for an HVAC company: air handling units (AHU), VRF systems, chillers and accessories.
It replaced a manual, Excel-based process with a database-backed system that calculates prices by fixed rules, keeps a full history, and exports branded Excel/PDF offers.

Built in two weeks (October 2026) by a non-developer working with an AI coding agent under strict written rules.

> **Showcase repository.** This is a cleaned copy of a private production project. Client data, real prices, the operational
> scripts and the internal documentation are not included, and the git history starts fresh. Tests that depend on private
> client files were removed, so 53 of the 149 tests are published here.

## What it does

1. **Upload**: a factory AHU selection file (.xlsx) is parsed automatically (`backend/app/ahu_parser.py`).
2. **Build**: lines come from the price-list catalog or a pasted Excel list (`bulk_lines.py`), and each line gets its own margin.
3. **Approve**: a responsible person locks the revision. Any later change creates a new revision.
4. **Export**: a branded Excel offer with a cover page, plus PDF (`kp_export.py`, `kp_pdf.py`).
5. **Track**: deal status, a dashboard, and a Telegram bot / Mini App.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite (24 pages, light/dark theme, phone layout) |
| Backend | Python, FastAPI |
| Database | PostgreSQL, Alembic (28 migrations, plain SQL) |
| Documents | openpyxl, pypdfium2, Edge headless for the cover |
| Access | Cloudflare Tunnel (HTTPS only), Telegram Mini App |

## Project layout

```
backend/
  app/
    main.py            app setup, security headers
    shield.py          outermost middleware: body-size and rate limits
    security.py        sessions, Argon2, two-factor codes
    guard.py           login/IP lockouts, admin alerts
    routers/           auth, quotations, kp_edit, price_list, deals, evidence, admin
    kp_service.py      offer business logic
    ahu_parser.py      factory AHU file reader (defusedxml, zip-bomb check)
    kp_export.py       Excel export
    kp_pdf.py          PDF with cover page
  migrations/sql/      schema, views, triggers (0001 … 0028)
  tests/               pytest, separate *_test database only
frontend/
  src/api.ts           single API client (HttpOnly cookie session)
  src/pages/           24 pages
  src/styles.css       design tokens for light and dark themes
```

## Business rules, as code

- Margin per line: `price / (1 − margin)`. Every line has its own margin.
- Rounding: full precision inside, `ROUNDUP` to a whole number at the end. `Decimal` / `NUMERIC` everywhere, never float.
- VAT is never added twice. Unclear cases become a "needs check" data issue instead of a guess.
- A missing price is never invented. Every price keeps its source (file, sheet, date).
- Approved offers are locked by database triggers, and every change is written to an append-only audit log.

## Security

| Threat | Defense |
|---|---|
| Password guessing | 5 failures lock the login for 15 minutes; 20 from one IP block the IP (stored in the database) |
| Stolen session | Server-side sessions, 60-minute idle and 8-hour limits, admin can end sessions |
| Request floods | Per-IP limits (30/min for login, 600/min for the API), concurrency cap |
| Huge uploads | Body-size limit checked before authentication |
| Malicious Excel | `defusedxml` plus a zip-bomb check |
| XSS / clickjacking | Strict CSP, X-Frame-Options, nosniff, no inline scripts |
| SQL injection | Parameterized queries only |
| Login probing by timing | The same Argon2 check runs for unknown logins |

Admins also get two-factor login through Telegram and a separate secret word for the admin panel. Attacks trigger Telegram alerts.

## Running locally

Requirements: Python 3.12+, Node.js LTS, PostgreSQL.

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows; use .venv/bin on Linux/macOS
cp .env.example .env                              # then fill in your own values
cd backend && ../.venv/Scripts/alembic upgrade head
cd ../frontend && npm install && npm run build
```

Tests run only against a database whose name ends in `_test` (see `backend/tests/conftest.py`).

## Author

Sarvar Erkinjonov, AVENTOS. Published with the company's permission.

## License

All rights reserved. The code is shared for portfolio and learning purposes. Ask before reusing it.
