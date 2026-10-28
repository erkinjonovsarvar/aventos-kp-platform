"""Kirish / chiqish / joriy foydalanuvchi / 2 bosqichli kirish (Telegram kodi).

Xavfsizlik auditi 2026-10-17:
- Parol taxminidan himoya: bitta login uchun (har qanday IP dan) 5 ta noto'g'ri urinish -> 15 daqiqa blok;
  bitta IP dan 20 ta -> IP blok. Hisob auth_event jurnalida (server qayta yonsa ham saqlanadi).
- Muvaffaqiyatsiz urinishlar jurnalga yozilishi uchun xato javoblar exception emas, JSONResponse bilan qaytadi
  (aks holda tranzaksiya bekor bo'lib, yozuv yo'qoladi).
- Sessiya bazada (user_session); "Chiqish" bekor qiladi; "Barcha qurilmalardan chiqish".
"""
from functools import lru_cache

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..config import settings
from ..db import get_conn, set_actor
from ..deps import CurrentUser, current_user, load_user
from .. import telegram
from ..guard import (admin_word_locked, client_ip, expire_stale_sessions, ip_blocked, log_event, login_locked,
                     revoke_sessions)
from ..security import (code_hash, create_mfa_token, hash_password, new_link_code, new_numeric_code, new_session_token,
                        read_mfa_token, session_expiry, token_hash, verify_password)

router = APIRouter(prefix="/api/auth", tags=["Kirish"])
GENERIC_FAIL = "Login yoki parol noto'g'ri (yoki foydalanish muddati tugagan)"


def _fail(code: int, msg: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": msg})


@lru_cache
def _dummy_hash() -> str:
    return hash_password(new_link_code())


def _locked_msg() -> str:
    return f"Ko'p noto'g'ri urinish — {settings().login_lock_minutes} daqiqadan keyin qayta urining"


def _start_session(conn: Connection, request: Request, response: Response, user: CurrentUser, via: str | None = None) -> dict:
    """via — kirish yo'li (masalan "Telegram Mini App"): jurnalga yoziladi; Mini App da Telegram xabari yuborilmaydi
    (foydalanuvchi o'zi Telegram ichida, har ochilishda xabar keraksiz)."""
    expire_stale_sessions(conn)                     # eski (muddati o'tgan) sessiyalar yopiladi
    token, h = new_session_token()
    conn.execute(text(
        """INSERT INTO user_session (user_id, token_hash, expires_at, ip, user_agent)
           VALUES (:u, :h, :e, :ip, :ua)"""),
        {"u": user.id, "h": h, "e": session_expiry(), "ip": client_ip(request), "ua": request.headers.get("user-agent", "")[:300]})
    set_actor(conn, user.id)
    conn.execute(text("UPDATE app_user SET last_login_at = now() WHERE id = :id"), {"id": user.id})
    log_event(conn, "login_ok", request, login=user.login, user_id=user.id, details=via)
    if via is None:
        chat = conn.execute(text("SELECT telegram_chat_id FROM app_user WHERE id = :u"), {"u": user.id}).scalar()
        telegram.notify(chat, f"🔐 AVENTOS KP: yangi kirish ({user.login})\nIP: {client_ip(request)}\n"
                              f"Qurilma: {request.headers.get('user-agent', '?')[:120]}\n"
                              "Siz bo'lmasangiz — darhol «Barcha qurilmalardan chiqish» ni bosing va parolni almashtiring.")
    https = request.url.scheme == "https"           # tunnel/proksi orqali (X-Forwarded-Proto) — uvicorn hisobga oladi
    response.set_cookie(settings().cookie_name, token, httponly=True, samesite="strict",
                        secure=settings().cookie_secure or https, max_age=settings().access_token_hours * 3600)
    return user.as_dict()


class LoginIn(BaseModel):
    login: str = Field(max_length=120)
    password: str = Field(max_length=200)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, conn: Connection = Depends(get_conn, scope="function")):
    ip = client_ip(request)
    if ip_blocked(conn, ip):
        log_event(conn, "ip_blocked", request, login=body.login)
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    if login_locked(conn, body.login):
        log_event(conn, "login_locked", request, login=body.login)
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    u = conn.execute(text("SELECT id, password_hash FROM app_user WHERE lower(login) = lower(:l)"), {"l": body.login}).first()
    # Login yo'q bo'lsa ham Argon2 tekshiruvi bajariladi — javob vaqtidan login borligini bilib bo'lmasin (2026-10-22)
    ok = verify_password(body.password, u.password_hash if u else _dummy_hash())
    user = load_user(conn, u.id) if u and ok else None
    if user is None:
        # Login yo'qmi, parol xatomi, muddat tugaganmi — ataylab bir xil javob
        log_event(conn, "login_failed", request, login=body.login, user_id=u.id if u else None)
        return _fail(status.HTTP_401_UNAUTHORIZED, GENERIC_FAIL)
    if user.mfa_enabled:
        err = _send_code(conn, request, user.id, user.login, "login")
        if err:
            return err
        return {"mfa_required": True, "mfa_token": create_mfa_token(user.id), "channel": "telegram",
                "telegram_name": user.telegram_name}
    return _start_session(conn, request, response, user)


def _send_code(conn: Connection, request: Request, user_id: int, login: str, purpose: str) -> JSONResponse | None:
    """Yangi 6 xonali kod -> Telegram (avvalgi ishlatilmagan kodlar bekor). Xato bo'lsa JSONResponse."""
    last = conn.execute(text(
        """SELECT now() - max(created_at) < interval '30 seconds' FROM telegram_code
           WHERE user_id = :u AND purpose = :p"""), {"u": user_id, "p": purpose}).scalar()
    if last:
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, "Kod hozirgina yuborildi — 30 soniyadan keyin qayta so'rang")
    chat = conn.execute(text("SELECT telegram_chat_id FROM app_user WHERE id = :u"), {"u": user_id}).scalar()
    code = new_numeric_code()
    conn.execute(text("UPDATE telegram_code SET used_at = now() WHERE user_id = :u AND purpose = :p AND used_at IS NULL"),
                 {"u": user_id, "p": purpose})
    conn.execute(text(
        """INSERT INTO telegram_code (user_id, purpose, code_hash, expires_at)
           VALUES (:u, :p, :h, now() + make_interval(mins => :m))"""),
        {"u": user_id, "p": purpose, "h": code_hash(user_id, purpose, code), "m": settings().login_code_minutes})
    what = "kirish" if purpose == "login" else "Telegram'ni uzish"
    if not chat or not telegram.send_message(chat, f"AVENTOS KP {what} kodi: {code}\n"
                                                   f"{settings().login_code_minutes} daqiqa amal qiladi. Kodni hech kimga aytmang."):
        return _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "Telegram'ga kod yuborib bo'lmadi — birozdan keyin qayta urining")
    log_event(conn, "mfa_required", request, login=login, user_id=user_id, details=f"telegram: {purpose}")
    return None


def _check_code(conn: Connection, user_id: int, purpose: str, code: str) -> bool:
    """Oxirgi ishlatilmagan, muddati o'tmagan kod; 5 noto'g'ri urinishdan keyin kod yaroqsiz."""
    row = conn.execute(text(
        """SELECT id, code_hash FROM telegram_code WHERE user_id = :u AND purpose = :p AND used_at IS NULL
             AND expires_at > now() AND attempts < 5 ORDER BY id DESC LIMIT 1"""), {"u": user_id, "p": purpose}).first()
    if row is None:
        return False
    if code_hash(user_id, purpose, (code or "").replace(" ", "")) == row.code_hash:
        conn.execute(text("UPDATE telegram_code SET used_at = now() WHERE id = :i"), {"i": row.id})
        return True
    conn.execute(text("UPDATE telegram_code SET attempts = attempts + 1 WHERE id = :i"), {"i": row.id})
    return False


class MfaIn(BaseModel):
    mfa_token: str = Field(max_length=2000)
    code: str = Field(max_length=10)


@router.post("/mfa")
def login_mfa(body: MfaIn, request: Request, response: Response, conn: Connection = Depends(get_conn, scope="function")):
    """2-bosqich: Telegram'ga yuborilgan 6 xonali kod."""
    uid = read_mfa_token(body.mfa_token)
    row = conn.execute(text("SELECT login FROM app_user WHERE id = :u AND telegram_chat_id IS NOT NULL"),
                       {"u": uid}).first() if uid else None
    if row is None:
        return _fail(status.HTTP_401_UNAUTHORIZED, "Kirish muddati o'tdi — login va parolni qayta kiriting")
    if ip_blocked(conn, client_ip(request)) or login_locked(conn, row.login):
        log_event(conn, "login_locked", request, login=row.login, user_id=uid)
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    user = load_user(conn, uid)
    if user is None or not _check_code(conn, uid, "login", body.code):
        log_event(conn, "mfa_failed", request, login=row.login, user_id=uid)
        return _fail(status.HTTP_401_UNAUTHORIZED, "Kod noto'g'ri yoki eskirgan")
    return _start_session(conn, request, response, user)


class MfaTokenIn(BaseModel):
    mfa_token: str = Field(max_length=2000)


@router.post("/mfa/resend")
def login_mfa_resend(body: MfaTokenIn, request: Request, conn: Connection = Depends(get_conn, scope="function")):
    """Kodni qayta yuborish (30 soniyada bir marta)."""
    uid = read_mfa_token(body.mfa_token)
    login = conn.execute(text("SELECT login FROM app_user WHERE id = :u AND telegram_chat_id IS NOT NULL"),
                         {"u": uid}).scalar() if uid else None
    if login is None:
        return _fail(status.HTTP_401_UNAUTHORIZED, "Kirish muddati o'tdi — login va parolni qayta kiriting")
    if ip_blocked(conn, client_ip(request)) or login_locked(conn, login):
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    return _send_code(conn, request, uid, login, "login") or {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, conn: Connection = Depends(get_conn, scope="function")):
    token = request.cookies.get(settings().cookie_name)
    if token:
        row = conn.execute(text(
            """UPDATE user_session SET revoked_at = now(), revoked_reason = 'logout'
               WHERE token_hash = :h AND revoked_at IS NULL RETURNING user_id"""), {"h": token_hash(token)}).first()
        if row:
            log_event(conn, "logout", request, user_id=row.user_id)
    response.delete_cookie(settings().cookie_name)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, user: CurrentUser = Depends(current_user),
               conn: Connection = Depends(get_conn, scope="function")):
    """Barcha qurilmalardan chiqish (telefon yo'qolsa va h.k.)."""
    n = revoke_sessions(conn, user.id, "logout_all")
    log_event(conn, "sessions_revoked", request, login=user.login, user_id=user.id, details=f"o'zi: {n} ta sessiya")
    response.delete_cookie(settings().cookie_name)
    return {"ok": True, "revoked": n}


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)):
    return user.as_dict()


@router.get("/sessions")
def my_sessions(user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    rows = conn.execute(text(
        """SELECT id, created_at, last_seen_at, ip, user_agent, token_hash = :h AS current FROM user_session
           WHERE user_id = :u AND revoked_at IS NULL AND expires_at > now()
             AND last_seen_at > now() - make_interval(mins => :idle) ORDER BY last_seen_at DESC"""),
        {"u": user.id, "h": user.session_hash, "idle": settings().session_idle_minutes}).mappings().all()
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]


# ------------------------------------------------------------------ Telegram'ni ulash / uzish
class WebAppIn(BaseModel):
    init_data: str = Field(min_length=10, max_length=4096)


@router.post("/telegram/webapp")
def telegram_webapp_login(body: WebAppIn, request: Request, response: Response,
                          conn: Connection = Depends(get_conn, scope="function")):
    """Platforma bot ichida (Telegram Mini App) ochilganda avtomatik kirish (foydalanuvchi qarori 2026-10-21):
    Telegram imzosi (initData, bot kaliti bilan) tekshiriladi va Telegram'i ulangan faol xodim tanlanadi.
    Parol so'ralmaydi — Telegram akkaunti egasi = xodim. Jurnalda "Telegram Mini App" deb belgilanadi."""
    ip = client_ip(request)
    if ip_blocked(conn, ip):
        log_event(conn, "ip_blocked", request, details="telegram mini app")
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    try:
        tg_user = telegram.verify_webapp(body.init_data)
    except telegram.TelegramError as e:
        log_event(conn, "login_failed", request, details=f"telegram mini app: {e}")
        return _fail(status.HTTP_401_UNAUTHORIZED, "Telegram tasdig'i noto'g'ri yoki eskirgan — botni yopib, qayta oching")
    uid = conn.execute(text("SELECT id FROM app_user WHERE telegram_chat_id = :c"), {"c": tg_user["id"]}).scalar()
    user = load_user(conn, uid) if uid else None
    if user is None:
        log_event(conn, "login_failed", request, user_id=uid, details=f"telegram mini app: ulanmagan yoki nofaol ({tg_user['id']})")
        return _fail(status.HTTP_403_FORBIDDEN, "Bu Telegram hisobi platformadagi faol foydalanuvchiga ulanmagan. "
                                                "Avval saytda login va parol bilan kirib, «Telegram'ni ulash» ni bosing.")
    if login_locked(conn, user.login):
        log_event(conn, "login_locked", request, login=user.login, user_id=user.id, details="telegram mini app")
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    return _start_session(conn, request, response, user, via="Telegram Mini App")


@router.post("/telegram/link")
def telegram_link(user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """Bir martalik havola (10 daqiqa): t.me/<bot>?start=<kod>. Xodim Telegram'da Start bosganda ulanadi."""
    if user.mfa_enabled:
        return _fail(status.HTTP_409_CONFLICT, "Telegram allaqachon ulangan")
    bot = telegram.bot_username()
    if not bot:
        return _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "Telegram bot hali sozlanmagan — adminga murojaat qiling")
    code = new_link_code()
    conn.execute(text("UPDATE telegram_code SET used_at = now() WHERE user_id = :u AND purpose = 'link' AND used_at IS NULL"),
                 {"u": user.id})
    conn.execute(text(
        """INSERT INTO telegram_code (user_id, purpose, code_hash, expires_at)
           VALUES (:u, 'link', :h, now() + make_interval(mins => :m))"""),
        {"u": user.id, "h": code_hash(0, "link", code), "m": telegram.LINK_MINUTES})
    return {"url": f"https://t.me/{bot}?start={code}", "bot": bot, "minutes": telegram.LINK_MINUTES}


@router.post("/telegram/unlink-code")
def telegram_unlink_code(request: Request, user: CurrentUser = Depends(current_user),
                         conn: Connection = Depends(get_conn, scope="function")):
    if not user.mfa_enabled:
        return _fail(status.HTTP_409_CONFLICT, "Telegram ulanmagan")
    return _send_code(conn, request, user.id, user.login, "unlink") or {"ok": True}


class UnlinkIn(BaseModel):
    code: str = Field(max_length=10)
    password: str = Field(max_length=200)


@router.post("/telegram/unlink")
def telegram_unlink(body: UnlinkIn, request: Request, user: CurrentUser = Depends(current_user),
                    conn: Connection = Depends(get_conn, scope="function")):
    """Uzish: parol + Telegram'ga kelgan kod (sessiyasi o'g'irlangan odam uza olmasin)."""
    row = conn.execute(text("SELECT password_hash, telegram_chat_id FROM app_user WHERE id = :u AND telegram_chat_id IS NOT NULL"),
                       {"u": user.id}).first()
    if row is None:
        return _fail(status.HTTP_409_CONFLICT, "Telegram ulanmagan")
    if not verify_password(body.password, row.password_hash) or not _check_code(conn, user.id, "unlink", body.code):
        log_event(conn, "mfa_failed", request, login=user.login, user_id=user.id, details="uzishga urinish")
        return _fail(status.HTTP_401_UNAUTHORIZED, "Parol yoki kod noto'g'ri")
    conn.execute(text("UPDATE app_user SET telegram_chat_id = NULL, telegram_name = NULL, telegram_linked_at = NULL WHERE id = :u"),
                 {"u": user.id})
    log_event(conn, "mfa_disabled", request, login=user.login, user_id=user.id, details="telegram")
    telegram.notify(row.telegram_chat_id, f"AVENTOS KP: Telegram {user.login} hisobidan uzildi.")
    return {"ok": True}


# ------------------------------------------------------------------ admin paneli uchun maxfiy so'z
# Foydalanuvchi talabi (2026-10-17): admin paneliga kirish uchun faqat admin o'zi biladigan qo'shimcha so'z.
# Bazada faqat Argon2 hash. Sessiyada admin_unlock_minutes harakatsizlikdan keyin qayta so'raladi.
# admin_word_max_attempts ta noto'g'ri urinish -> shu foydalanuvchining barcha sessiyalari yopiladi va blok.
class AdminWordSetIn(BaseModel):
    password: str = Field(max_length=200)
    word: str = Field(min_length=8, max_length=200)
    current_word: str | None = Field(None, max_length=200)


class AdminWordIn(BaseModel):
    word: str = Field(max_length=200)


def _unlock(conn: Connection, user: CurrentUser) -> dict:
    conn.execute(text("UPDATE user_session SET admin_unlocked_at = now() WHERE token_hash = :h"), {"h": user.session_hash})
    user.admin_word_set = user.admin_unlocked = True
    return user.as_dict()


@router.post("/admin-word/set")
def admin_word_set(body: AdminWordSetIn, request: Request, user: CurrentUser = Depends(current_user),
                   conn: Connection = Depends(get_conn, scope="function")):
    """Maxfiy so'zni o'rnatish yoki almashtirish (almashtirishda eski so'z ham so'raladi)."""
    if not user.can("user.manage"):
        return _fail(status.HTTP_403_FORBIDDEN, "Faqat admin uchun")
    if admin_word_locked(conn, user.id):
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    row = conn.execute(text("SELECT password_hash, admin_word_hash FROM app_user WHERE id = :u"), {"u": user.id}).first()
    if not verify_password(body.password, row.password_hash) or (
            row.admin_word_hash and not verify_password(body.current_word or "", row.admin_word_hash)):
        log_event(conn, "admin_word_failed", request, login=user.login, user_id=user.id, details="o'rnatishga urinish")
        return _fail(status.HTTP_401_UNAUTHORIZED, "Parol yoki joriy maxfiy so'z noto'g'ri")
    if body.word.strip() != body.word or len(set(body.word)) < 4:
        return _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "Maxfiy so'z juda oddiy (bosh/oxirida bo'sh joy bo'lmasin, kamida 4 xil belgi)")
    if verify_password(body.word, row.password_hash):
        return _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "Maxfiy so'z parol bilan bir xil bo'lmasin")
    conn.execute(text("UPDATE app_user SET admin_word_hash = :h, admin_word_set_at = now() WHERE id = :u"),
                 {"h": hash_password(body.word), "u": user.id})
    conn.execute(text("UPDATE user_session SET admin_unlocked_at = NULL WHERE user_id = :u"), {"u": user.id})
    log_event(conn, "admin_word_set", request, login=user.login, user_id=user.id)
    return _unlock(conn, user)


@router.post("/admin-word/verify")
def admin_word_verify(body: AdminWordIn, request: Request, user: CurrentUser = Depends(current_user),
                      conn: Connection = Depends(get_conn, scope="function")):
    if not user.can("user.manage"):
        return _fail(status.HTTP_403_FORBIDDEN, "Faqat admin uchun")
    h = conn.execute(text("SELECT admin_word_hash FROM app_user WHERE id = :u"), {"u": user.id}).scalar()
    if not h:
        return _fail(status.HTTP_409_CONFLICT, "Avval maxfiy so'z o'rnating")
    if admin_word_locked(conn, user.id):
        log_event(conn, "admin_word_locked", request, login=user.login, user_id=user.id)
        return _fail(status.HTTP_429_TOO_MANY_REQUESTS, _locked_msg())
    if verify_password(body.word, h):
        log_event(conn, "admin_word_ok", request, login=user.login, user_id=user.id)
        return _unlock(conn, user)
    log_event(conn, "admin_word_failed", request, login=user.login, user_id=user.id)
    if admin_word_locked(conn, user.id):
        n = revoke_sessions(conn, user.id, "admin_word_failed")
        log_event(conn, "sessions_revoked", request, login=user.login, user_id=user.id,
                  details=f"noto'g'ri maxfiy so'z: {n} ta sessiya yopildi")
        log_event(conn, "admin_word_locked", request, login=user.login, user_id=user.id)
        return _fail(status.HTTP_401_UNAUTHORIZED, "Ko'p noto'g'ri urinish — xavfsizlik uchun barcha qurilmalardan chiqarildingiz. "
                     f"{settings().login_lock_minutes} daqiqadan keyin qayta kiring.")
    return _fail(status.HTTP_401_UNAUTHORIZED, "Maxfiy so'z noto'g'ri")


@router.post("/admin-word/lock")
def admin_word_lock(user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """Admin panelni darhol qulflash (keyingi safar yana so'z so'raladi)."""
    conn.execute(text("UPDATE user_session SET admin_unlocked_at = NULL WHERE token_hash = :h"), {"h": user.session_hash})
    user.admin_unlocked = False
    return user.as_dict()
