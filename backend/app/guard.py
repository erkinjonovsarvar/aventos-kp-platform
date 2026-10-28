"""Xavfsizlik jurnali (auth_event) va unga asoslangan cheklovlar: parol taxmini, IP blok, taklif havolasi spami."""
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .config import settings

MFA_ROLES = ("admin", "director")              # 2 bosqichli kirish majburiy tavsiya qilinadigan rollar


def client_ip(request: Request) -> str:
    """Haqiqiy mijoz IP si: Cloudflare tunnel orqali CF-Connecting-IP, aks holda uvicorn aniqlagani."""
    if request.client and request.client.host in ("127.0.0.1", "::1"):
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()[:64]
    return (request.client.host if request.client else "")[:64]


# Hujum belgilari — adminlarga darhol Telegram xabari (2026-10-22). Bir xil hodisa (tur + IP/login) 15 daqiqada bir marta.
ALERT_EVENTS = {"ip_blocked": "IP bloklandi (ko'p noto'g'ri parol)", "login_locked": "login bloklandi (ko'p noto'g'ri urinish)",
                "admin_word_locked": "admin maxfiy so'zi bloklandi", "join_blocked": "taklif havolasi tokeni taxmin qilinmoqda"}
ALERT_EVERY = 15 * 60
_alerted: dict[str, float] = {}


def alert_admins(key: str, message: str) -> None:
    """Telegram'i ulangan barcha faol adminlarga xabar (fon oqimida, javob kutilmaydi)."""
    import threading
    import time

    from . import telegram
    now = time.monotonic()
    if not settings().telegram_bot_token or now - _alerted.get(key, -ALERT_EVERY) < ALERT_EVERY:
        return
    _alerted[key] = now
    if len(_alerted) > 5000:                                   # xotira to'lmasin
        _alerted.clear()

    def run():
        from .db import engine
        try:
            with engine().connect() as c:
                chats = [r[0] for r in c.execute(text(
                    """SELECT DISTINCT u.telegram_chat_id FROM v_active_user a JOIN app_user u ON u.id = a.user_id
                       JOIN user_role r ON r.user_id = u.id WHERE r.role_code = 'admin' AND u.telegram_chat_id IS NOT NULL"""))]
        except Exception:                                      # noqa: BLE001 — ogohlantirish xatosi asosiy ishni to'xtatmasin
            return
        for chat in chats:
            telegram.send_message(chat, message)
    threading.Thread(target=run, daemon=True).start()


def log_event(conn: Connection, event: str, request: Request | None = None, login: str | None = None,
              user_id: int | None = None, details: str | None = None) -> None:
    if event in ALERT_EVENTS:
        ip = client_ip(request) if request else "?"
        alert_admins(f"{event}:{ip}:{(login or '').lower()}",
                     f"⚠️ AVENTOS KP: {ALERT_EVENTS[event]}\nLogin: {login or '—'}\nIP: {ip}\n"
                     "Siz bo'lmasangiz — Xavfsizlik jurnalini tekshiring.")
    conn.execute(text(
        """INSERT INTO auth_event (event, login, user_id, ip, user_agent, details)
           VALUES (:e, :l, :u, :ip, :ua, :d)"""),
        {"e": event, "l": (login or None) and login[:120], "u": user_id, "ip": client_ip(request) if request else None,
         "ua": (request.headers.get("user-agent", "")[:300] if request else None), "d": details})


def login_locked(conn: Connection, login: str) -> bool:
    """Shu login bo'yicha (IP dan qat'i nazar) oxirgi muvaffaqiyatli kirishdan keyin ketma-ket noto'g'ri urinishlar."""
    n = conn.execute(text(
        """SELECT count(*) FROM auth_event e
           WHERE e.event IN ('login_failed', 'mfa_failed') AND lower(e.login) = lower(:l)
             AND e.at > now() - make_interval(mins => :m)
             AND e.at > coalesce((SELECT max(at) FROM auth_event s WHERE s.event = 'login_ok' AND lower(s.login) = lower(:l)), '-infinity')"""),
        {"l": login, "m": settings().login_lock_minutes}).scalar_one()
    return n >= settings().login_max_attempts


def ip_blocked(conn: Connection, ip: str) -> bool:
    n = conn.execute(text(
        """SELECT count(*) FROM auth_event WHERE event IN ('login_failed', 'mfa_failed') AND ip = :ip
             AND at > now() - make_interval(mins => :m)"""),
        {"ip": ip, "m": settings().login_lock_minutes}).scalar_one()
    return bool(ip) and n >= settings().ip_max_attempts


def join_blocked(conn: Connection, ip: str) -> bool:
    n = conn.execute(text(
        "SELECT count(*) FROM auth_event WHERE event = 'join_invalid' AND ip = :ip AND at > now() - interval '1 hour'"),
        {"ip": ip}).scalar_one()
    return bool(ip) and n >= settings().join_max_invalid


def revoke_sessions(conn: Connection, user_id: int, reason: str, except_hash: str | None = None) -> int:
    return conn.execute(text(
        """UPDATE user_session SET revoked_at = now(), revoked_reason = :r
           WHERE user_id = :u AND revoked_at IS NULL AND (CAST(:x AS text) IS NULL OR token_hash <> :x)"""),
        {"u": user_id, "r": reason, "x": except_hash}).rowcount


def expire_stale_sessions(conn: Connection) -> int:
    """Muddati yoki harakatsizlik vaqti o'tgan, lekin bekor qilinmagan sessiyalarni 'expired' deb yopish (2026-10-20).
    Kirish tekshiruvi (deps.current_user) ularni baribir qabul qilmaydi — bu faqat tartib: "faol sessiyalar" ro'yxati to'g'ri bo'lsin."""
    return conn.execute(text(
        """UPDATE user_session SET revoked_at = now(), revoked_reason = 'expired'
           WHERE revoked_at IS NULL AND (expires_at <= now() OR last_seen_at <= now() - make_interval(mins => :idle))"""),
        {"idle": settings().session_idle_minutes}).rowcount


def admin_word_locked(conn: Connection, user_id: int) -> bool:
    """Admin maxfiy so'zi: oxirgi to'g'ri kiritishdan keyin login_lock_minutes ichida noto'g'ri urinishlar soni."""
    n = conn.execute(text(
        """SELECT count(*) FROM auth_event e
           WHERE e.event = 'admin_word_failed' AND e.user_id = :u AND e.at > now() - make_interval(mins => :m)
             AND e.id > coalesce((SELECT max(id) FROM auth_event s WHERE s.event IN ('admin_word_ok', 'admin_word_set')
                                  AND s.user_id = :u), 0)"""),
        {"u": user_id, "m": settings().login_lock_minutes}).scalar_one()
    return n >= settings().admin_word_max_attempts
