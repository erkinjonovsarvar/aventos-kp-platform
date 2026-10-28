"""Sozlamalar: hammasi .env dan (parollar kodda yo'q).
KP_ENV_FILE muhit o'zgaruvchisi boshqa faylni tanlaydi (masalan testlar uchun .env.test — alohida test bazasi)."""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def env_file() -> Path:
    """Ishlatiladigan sozlama fayli: KP_ENV_FILE yoki standart D:/KP_AGENT/.env."""
    return Path(os.environ["KP_ENV_FILE"]) if os.environ.get("KP_ENV_FILE") else ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_file(), extra="ignore")

    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    secret_key: str

    access_token_hours: int = 8
    cookie_name: str = "kp_session"
    cookie_secure: bool = False          # True — har doim faqat HTTPS; False — so'rov HTTPS bo'lsa avtomatik Secure
    login_max_attempts: int = 5          # bitta login uchun (har qanday IP dan) — keyin login_lock_minutes ga blok
    login_lock_minutes: int = 15
    ip_max_attempts: int = 20            # bitta IP dan (har qanday login) noto'g'ri urinishlar — keyin IP blok
    session_idle_minutes: int = 60       # harakatsizlikdan keyin sessiya tugaydi (xavfsizlik auditi 2026-10-17)
    telegram_bot_token: str = ""         # 2 bosqichli kirish kodlari (@BotFather dan); bo'sh — Telegram o'chiq
    edge_path: str = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"   # PDF muqova (Chromium)
    login_code_minutes: int = 5          # Telegram'ga yuborilgan kirish kodi amal qilish muddati
    admin_unlock_minutes: int = 15       # admin paneli: maxfiy so'z shu daqiqa harakatsizlikdan keyin qayta so'raladi
    admin_word_max_attempts: int = 5     # noto'g'ri maxfiy so'z -> barcha sessiyalar yopiladi, blok
    join_max_invalid: int = 10           # taklif havolasi: bitta IP dan soatiga noto'g'ri token urinishlari
    invitation_hours_default: int = 72
    public_base_url: str = ""             # bo'sh — havola so'rov kelgan manzildan (tunnel/domen) yasaladi
    expose_docs: bool = False            # /docs (API sinov sahifasi) — internetga chiqqanda yopiq; lokalda .env da EXPOSE_DOCS=true
    # Excel'da yaratilgan KP lar papkasi (D:\Quotations\<KP>\) — yangi KP raqami ular bilan to'qnashmasligi uchun.
    # Bo'sh qoldirilsa (masalan, serverda) faqat baza hisobga olinadi.
    quotations_dir: str = r"D:\Quotations"
    # Shu raqamdan keyingi bo'sh raqamlar to'ldiriladi (o'chirilgan KP raqami qayta beriladi). 1002107 — Excel'dagi oxirgi KP;
    # undan oldingi bo'shliqlar import qilinmagan eski KP lar, ularga tegilmaydi.
    kp_number_floor: int = 1002107


@lru_cache
def settings() -> Settings:
    return Settings()
