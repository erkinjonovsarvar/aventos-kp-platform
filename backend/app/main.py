"""AVENTOS KP Management System — backend API.

Ishga tushirish (D:\\KP_AGENT papkasidan):
    .venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --port 8000
Veb-interfeys: http://localhost:8000   ·   API hujjati: http://localhost:8000/docs
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import shield, telegram
from .config import settings
from .routers import admin, auth, deals, evidence, kp_edit, price_list, quotations

_docs = settings().expose_docs
app = FastAPI(
    docs_url="/docs" if _docs else None, redoc_url=None, openapi_url="/openapi.json" if _docs else None,
    title="AVENTOS KP Management System",
    version="0.1.0",
    description="Tijoriy takliflar (KP), chegirma hisobotlari va foydalanuvchilar. "
                "Avval **POST /api/auth/login** orqali kiring — sessiya cookie'da saqlanadi.",
)
@app.middleware("http")
async def https_only_from_internet(request: Request, call_next):
    """Tunnel/proksi orqali (internetdan) shifrlanmagan http so'rov — https ga yo'naltiriladi (parol ochiq ketmasin).
    Kompyuterning o'zidan to'g'ridan-to'g'ri (localhost, proksi sarlavhasisiz) kirish avvalgidek ishlaydi."""
    if request.headers.get("x-forwarded-proto") == "http" or (
            request.headers.get("cf-visitor", "").find('"http"') >= 0):
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    response = await call_next(request)
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    # Brauzer himoya sarlavhalari (xavfsizlik auditi 2026-10-17): faqat o'z manbalaridan kod/ulanish, begona saytga
    # joylashtirish (clickjacking) taqiqlangan, MIME taxmin qilinmaydi, havola manzili tashqariga berilmaydi.
    h = response.headers
    h["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                    "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
                                    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
    h["X-Frame-Options"] = "DENY"
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    h["X-Permitted-Cross-Domain-Policies"] = "none"
    if request.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"                # KP, narx, foydalanuvchi ma'lumotlari brauzer keshida qolmasin
    return response


# Eng tashqi qatlam (oxirida qo'shilgan — birinchi ishlaydi): so'rov hajmi va IP bo'yicha so'rovlar soni (shield.py)
app.add_middleware(shield.Shield)


@app.on_event("startup")
def _telegram_bot():
    telegram.start_polling()            # 2 bosqichli kirish boti (token .env da bo'lsa)


app.include_router(auth.router)
app.include_router(quotations.router)
app.include_router(kp_edit.router)
app.include_router(evidence.router)
app.include_router(deals.router)
app.include_router(price_list.router)
app.include_router(admin.admin)
app.include_router(admin.public)


@app.get("/api/health", tags=["Tizim"])
def health():
    return {"status": "ok"}


# --- Veb-interfeys (frontend/dist). Avval: cd frontend && npm run build
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (FRONTEND / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bunday API yo'q")
        # public/ dagi fayllar (logo.png, icon.png) — faqat dist ning yuqori papkasidan, yo'l chiqib ketmasin
        if path and "/" not in path and "\\" not in path and (FRONTEND / path).is_file():
            return FileResponse(FRONTEND / path, headers={"Cache-Control": "max-age=86400"})
        # Sahifa yo'llari (/login, /kp/123, /join/<token> ...) — hammasi bitta index.html (React o'zi yo'naltiradi)
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
