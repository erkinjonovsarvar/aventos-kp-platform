"""Parollar (Argon2), bazadagi sessiyalar, 2 bosqichli kirish (Telegram kodi), taklif havolasi tokenlari.

Xavfsizlik auditi 2026-10-17 (SECURITY_AUDIT_2026-10-17.md):
- Sessiya cookie sida faqat tasodifiy token (256-bit); bazada uning SHA-256 hash'i (user_session) — "Chiqish" va admin bekor qila oladi.
- 2FA: parol to'g'ri bo'lsa Telegram'ga 6 xonali kod (5 daqiqa, 5 urinish); bazada faqat HMAC (telegram.py, routers/auth.py).
- Parol taxminidan himoya auth_event jurnaliga asoslanadi (routers/auth.py) — server qayta yonsa ham saqlanadi.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.hash import argon2

from .config import settings

ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return argon2.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return argon2.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------ sessiyalar
def new_session_token() -> tuple[str, str]:
    """(cookie dagi token, bazadagi hash)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=settings().access_token_hours)


# 2-bosqich (kod) uchun qisqa muddatli belgi: parol to'g'ri, lekin sessiya hali yo'q
def create_mfa_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "purpose": "mfa", "iat": now, "exp": now + timedelta(minutes=5)},
                      settings().secret_key, algorithm=ALGORITHM)


def read_mfa_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, settings().secret_key, algorithms=[ALGORITHM])
        return int(data["sub"]) if data.get("purpose") == "mfa" else None
    except (JWTError, KeyError, ValueError):
        return None


# ------------------------------------------------------------------ taklif havolasi
def new_invitation_token() -> tuple[str, str]:
    """(havoladagi token, bazaga yoziladigan hash). Token faqat bir marta ko'rsatiladi."""
    token = secrets.token_urlsafe(32)
    return token, invitation_hash(token)


def invitation_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ 2FA (Telegram kodlari)
def new_numeric_code() -> str:
    """6 xonali kirish kodi (kriptografik tasodifiy)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def new_link_code() -> str:
    """Telegram /start uchun bir martalik kod (t.me/<bot>?start=... — faqat A-Z a-z 0-9 _ -)."""
    return secrets.token_urlsafe(16)


def code_hash(user_id: int, purpose: str, code: str) -> str:
    """Kod bazada ochiq saqlanmaydi: HMAC-SHA256 (SECRET_KEY). Ulash kodi foydalanuvchiga bog'lanmagan (user_id=0)."""
    msg = f"{purpose}:{user_id}:{code.strip()}".encode()
    return hmac.new(("aventos-tg:" + settings().secret_key).encode(), msg, hashlib.sha256).hexdigest()
