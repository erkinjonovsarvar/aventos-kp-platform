"""Telegram bot: 2 bosqichli kirish kodlari va xavfsizlik xabarlari (foydalanuvchi talabi 2026-10-17).

- Bot tokeni .env da (TELEGRAM_BOT_TOKEN) — kodda yo'q. Token bo'lmasa Telegram funksiyalari o'chiq.
- Server botga kelgan xabarlarni getUpdates (long polling) bilan o'qiydi — webhook/doimiy manzil kerak emas,
  internet havolasi (tunnel) o'zgarsa ham ishlaydi.
- Ulash: platforma bir martalik havola beradi (t.me/<bot>?start=<kod>); xodim Telegram'da Start bosadi -> chat ulanadi.
- Mini App (2026-10-21): botning menyu tugmasi platformani Telegram ichida ochadi; kirish — Telegram imzosi (initData)
  bilan avtomatik (foydalanuvchi qarori). /excel <KP> — KP ning Excel fayli chatga keladi.
"""
import hashlib
import hmac
import json
import logging
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .config import ROOT, settings
from .security import code_hash

log = logging.getLogger("aventos.telegram")
LINK_MINUTES = 10
WEBAPP_MAX_AGE = 3600            # Mini App imzosi (auth_date) shu soniyadan eski bo'lsa — qabul qilinmaydi
WEBAPP_BUTTON = "📋 KP platformasi"
LINK_FILE = ROOT / "scripts" / "havola.txt"     # start_all.ps1 yozadigan joriy internet havolasi (tunnel)


class TelegramError(Exception):
    pass


def _call(method: str, http_timeout: float = 15, **params) -> dict | list | bool:
    token = settings().telegram_bot_token
    if not token:
        raise TelegramError("Telegram bot sozlanmagan")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        data = json.loads(e.read() or b"{}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TelegramError(f"Telegram'ga ulanib bo'lmadi: {e.__class__.__name__}") from None
    if not data.get("ok"):
        raise TelegramError(f"Telegram xatosi: {data.get('description', '?')}")
    return data["result"]


def send_message(chat_id: int, message: str) -> bool:
    try:
        _call("sendMessage", chat_id=chat_id, text=message, disable_web_page_preview=True)
        return True
    except TelegramError as e:
        log.warning("Telegram xabar yuborilmadi: %s", e)
        return False


def notify(chat_id: int | None, message: str) -> None:
    """Javobni kutmasdan (fon oqimida) xabar yuborish — kirish sekinlashmasin."""
    if chat_id and settings().telegram_bot_token:
        threading.Thread(target=send_message, args=(chat_id, message), daemon=True).start()


@lru_cache
def _bot_username_cached(token: str) -> str | None:
    try:
        return _call("getMe")["username"]
    except TelegramError as e:
        log.warning("Telegram bot topilmadi: %s", e)
        return None


def bot_username() -> str | None:
    token = settings().telegram_bot_token
    return _bot_username_cached(token) if token else None


def send_document(chat_id: int, filename: str, data: bytes, caption: str = "") -> bool:
    """Faylni chatga yuborish (multipart/form-data)."""
    token = settings().telegram_bot_token
    if not token:
        return False
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    fname = urllib.parse.quote(filename)
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{fname}"; '
                  f"filename*=UTF-8''{fname}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendDocument", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return bool(json.loads(r.read()).get("ok"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        log.warning("Telegram fayl yuborilmadi: %s", e)
        return False


# ------------------------------------------------------------------ Mini App (platforma Telegram ichida)
def public_url() -> str | None:
    """Platformaning internetdagi manzili: .env PUBLIC_BASE_URL yoki tunnel havolasi (scripts/havola.txt). Faqat HTTPS."""
    url = settings().public_base_url.strip()
    if not url and LINK_FILE.exists():
        url = LINK_FILE.read_text(encoding="utf-8-sig", errors="ignore").strip()
    return url.rstrip("/") if url.startswith("https://") else None


def webapp_keyboard() -> dict | None:
    url = public_url()
    return {"inline_keyboard": [[{"text": WEBAPP_BUTTON, "web_app": {"url": url + "/"}}]]} if url else None


_menu_url: str | None = None


def sync_menu_button() -> None:
    """Botning menyu tugmasi joriy havolaga qarasin (tunnel qayta ochilsa havola o'zgaradi)."""
    global _menu_url
    url = public_url()
    if not url or url == _menu_url:
        return
    try:
        _call("setChatMenuButton", menu_button={"type": "web_app", "text": WEBAPP_BUTTON, "web_app": {"url": url + "/"}})
        _menu_url = url
        log.info("Telegram menyu tugmasi: %s", url)
    except TelegramError as e:
        log.warning("Telegram menyu tugmasi o'rnatilmadi: %s", e)


def verify_webapp(init_data: str, now: float | None = None) -> dict:
    """Telegram Mini App initData imzosini tekshirish (core.telegram.org/bots/webapps — "Validating data").
    Natija: Telegram foydalanuvchisi {id, username, ...}. Xato — TelegramError."""
    token = settings().telegram_bot_token
    if not token:
        raise TelegramError("Telegram bot sozlanmagan")
    pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    if not got or not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
        raise TelegramError("imzo noto'g'ri")
    try:
        age = (now or time.time()) - int(pairs.get("auth_date", "0"))
        user = json.loads(pairs.get("user", "{}"))
    except ValueError:
        raise TelegramError("ma'lumot buzilgan") from None
    if age > WEBAPP_MAX_AGE or age < -60:
        raise TelegramError("eskirgan")
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise TelegramError("foydalanuvchi yo'q")
    return user


# ------------------------------------------------------------------ botga kelgan xabarlar
NOT_LINKED = ("Telegram'ni ulash uchun platformada «Mening xavfsizligim» → «Telegram'ni ulash» tugmasini bosing "
              "va ochilgan havola orqali qayta kiring.")


def _linked_user(conn: Connection, chat_id: int):
    from .deps import load_user                       # aylana importdan qochish
    uid = conn.execute(text("SELECT id FROM app_user WHERE telegram_chat_id = :c"), {"c": chat_id}).scalar()
    return load_user(conn, uid) if uid else None      # faqat faol va muddati o'tmagan foydalanuvchi


def _with_app_button(message: str) -> dict | str:
    kb = webapp_keyboard()
    return {"text": message, "reply_markup": kb} if kb else message + "\n\n(Platforma havolasi hozir mavjud emas — server ishga tushirilsin.)"


def _excel(conn: Connection, user, arg: str) -> dict | str:
    """/excel <KP> — saytdagi «Excel yuklab olish» ning o'zi (huquq, menejer faqat o'z KP si, muqova — bir xil)."""
    from fastapi import HTTPException
    from .routers.quotations import export_xlsx
    if not arg.isdigit():
        return "Foydalanish: /excel 1002111"
    try:
        resp = export_xlsx(int(arg), None, "auto", False, False, True, user=user, conn=conn)
    except HTTPException as e:
        return f"KP {arg}: {e.detail}"
    disp = resp.headers.get("content-disposition", "")
    name = urllib.parse.unquote(disp.split("filename*=UTF-8''")[-1]) if "filename*=" in disp else f"{arg}.xlsx"
    return {"document": (name, bytes(resp.body)), "caption": f"KP {arg}"}


def handle_update(conn: Connection, update: dict) -> str | dict | None:
    """Bitta update ni qayta ishlash. Javob: matn yoki {"text", "reply_markup"} / {"document", "caption"} (yuborish — chaqiruvchida)."""
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":
        return None
    txt = (msg.get("text") or "").strip()
    chat_id = int(chat["id"])
    if not txt.startswith("/start") or not txt[6:].strip():
        user = _linked_user(conn, chat_id)
        if user is None:
            return NOT_LINKED if txt.startswith("/start") else "Bu AVENTOS KP boti. Kirish kodlari shu yerga keladi.\n\n" + NOT_LINKED
        if txt.lower().startswith("/excel"):
            return _excel(conn, user, txt[6:].strip())
        hint = "\nKP ning Excel fayli kerak bo'lsa: /excel <KP raqami>" if user.can("kp.download") else ""
        return _with_app_button(f"Assalomu alaykum, {user.full_name}!\nKP platformasini shu yerda ochish uchun pastdagi "
                                "tugmani bosing." + hint)
    payload = txt[6:].strip()
    row = conn.execute(text(
        """SELECT c.id, c.user_id, u.login FROM telegram_code c JOIN app_user u ON u.id = c.user_id
           WHERE c.purpose = 'link' AND c.used_at IS NULL AND c.expires_at > now() AND c.code_hash = :h"""),
        {"h": code_hash(0, "link", payload)}).first()
    if row is None:
        return "Havola eskirgan yoki noto'g'ri. Platformada «Telegram'ni ulash» ni qayta bosing."
    other = conn.execute(text("SELECT login FROM app_user WHERE telegram_chat_id = :c AND id <> :u"),
                         {"c": chat_id, "u": row.user_id}).scalar()
    if other:
        return "Bu Telegram hisobi boshqa foydalanuvchiga ulangan. Har xodim o'z Telegram'ini ulashi kerak."
    frm = msg.get("from") or {}
    name = ("@" + frm["username"]) if frm.get("username") else " ".join(
        x for x in (frm.get("first_name"), frm.get("last_name")) if x) or str(chat_id)
    conn.execute(text("UPDATE telegram_code SET used_at = now() WHERE id = :i"), {"i": row.id})
    conn.execute(text("""UPDATE app_user SET telegram_chat_id = :c, telegram_name = :n, telegram_linked_at = now()
                         WHERE id = :u"""), {"c": chat_id, "n": name[:100], "u": row.user_id})
    from .guard import log_event                        # aylana importdan qochish
    log_event(conn, "mfa_enabled", login=row.login, user_id=row.user_id, details=f"telegram {name}")
    return _with_app_button(f"✅ AVENTOS KP: Telegram ulandi ({row.login}).\n"
                            "Endi har kirishda tasdiqlash kodi shu yerga keladi. Kodni hech kimga aytmang.\n"
                            "Platformani shu yerda ochish — pastdagi tugma yoki chap pastdagi menyu.")


def _send_reply(chat_id: int, reply: str | dict) -> None:
    if isinstance(reply, str):
        send_message(chat_id, reply)
    elif "document" in reply:
        name, data = reply["document"]
        if not send_document(chat_id, name, data, reply.get("caption", "")):
            send_message(chat_id, "Faylni yuborib bo'lmadi — keyinroq qayta urinib ko'ring yoki saytdan yuklab oling.")
    else:
        try:
            _call("sendMessage", chat_id=chat_id, text=reply["text"], reply_markup=reply["reply_markup"],
                  disable_web_page_preview=True)
        except TelegramError as e:
            log.warning("Telegram xabar yuborilmadi: %s", e)


def _poll_forever() -> None:
    from .db import engine
    offset = 0
    while True:
        sync_menu_button()                              # havola o'zgargan bo'lsa — menyu tugmasi yangilanadi
        try:
            # long polling: Telegram 25 soniya kutadi, yangi xabar kelsa darhol qaytaradi
            updates = _call("getUpdates", http_timeout=40, offset=offset, timeout=25, allowed_updates=["message"])
        except TelegramError as e:
            log.warning("Telegram getUpdates: %s", e)
            time.sleep(10)
            continue
        for u in updates:
            offset = max(offset, u["update_id"] + 1)
            try:
                with engine().begin() as conn:
                    reply = handle_update(conn, u)
                chat_id = ((u.get("message") or {}).get("chat") or {}).get("id")
                if reply and chat_id:
                    _send_reply(chat_id, reply)
            except Exception:                          # bitta xabar xatosi botni to'xtatmasin
                log.exception("Telegram update xatosi")
        if not updates:
            time.sleep(1)


_started = False


def start_polling() -> None:
    """Server ishga tushganda (testlarda emas). Token bo'lmasa — hech narsa."""
    global _started
    if _started or not settings().telegram_bot_token or "pytest" in sys.modules:
        return
    _started = True
    threading.Thread(target=_poll_forever, name="telegram-poll", daemon=True).start()
