"""Xavfsizlik auditi 2026-10-17 tuzatishlari: bloklash, bazadagi sessiyalar, 2FA (Telegram), taklif havolasi cheklovi, sarlavhalar, zip-bomba."""
import io
import zipfile

import pytest
from sqlalchemy import text

from backend.app import telegram

from .test_api import TEST_PASSWORD, client, conn, login, make_user  # noqa: F401  (pytest fixture'lari)


def test_logout_revokes_session_and_idle_timeout(client, conn):
    make_user(conn, "t_sec", ["manager"])
    assert login(client, "t_sec").status_code == 200
    token = client.cookies.get("kp_session")
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    client.cookies.set("kp_session", token)                       # o'g'irlangan cookie — chiqishdan keyin ishlamaydi
    assert client.get("/api/auth/me").status_code == 401
    # harakatsizlik: 61 daqiqa so'rov bo'lmasa — sessiya tugaydi
    assert login(client, "t_sec").status_code == 200
    conn.execute(text("UPDATE user_session SET last_seen_at = now() - interval '61 minutes' WHERE revoked_at IS NULL"))
    assert client.get("/api/auth/me").status_code == 401


def test_login_lock_survives_ip_change_and_is_logged(client, conn):
    make_user(conn, "t_sec", ["manager"])
    for _ in range(5):
        assert login(client, "t_sec", "noto'g'ri-parol").status_code == 401
    r = login(client, "t_sec")                                      # to'g'ri parol ham — blok
    assert r.status_code == 429
    # boshqa IP dan ham (login bo'yicha blok)
    r = client.post("/api/auth/login", json={"login": "t_sec", "password": TEST_PASSWORD}, headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 429
    ev = dict(conn.execute(text("SELECT event, count(*) FROM auth_event WHERE login = 't_sec' GROUP BY 1")).all())
    assert ev["login_failed"] == 5 and ev["login_locked"] >= 1
    with pytest.raises(Exception), conn.begin_nested():
        conn.execute(text("DELETE FROM auth_event WHERE login = 't_sec'"))   # jurnalni o'chirib bo'lmaydi


def test_ip_block_after_many_logins(client, conn):
    for i in range(20):
        client.post("/api/auth/login", json={"login": f"yoq_{i}", "password": "x"})
    make_user(conn, "t_sec", ["manager"])
    assert login(client, "t_sec").status_code == 429                # shu IP dan — blok


@pytest.fixture
def tg(monkeypatch):
    """Telegram o'rniga: yuborilgan xabarlar ro'yxati (haqiqiy so'rov yo'q)."""
    sent = []
    monkeypatch.setattr(telegram, "send_message", lambda chat, msg: sent.append((chat, msg)) or True)
    monkeypatch.setattr(telegram, "notify", lambda chat, msg: chat and sent.append((chat, msg)))
    monkeypatch.setattr(telegram, "bot_username", lambda: "aventos_test_bot")
    return sent


def _start(conn, chat_id, payload, username="boss"):
    r = telegram.handle_update(conn, {"update_id": 1, "message": {
        "chat": {"id": chat_id, "type": "private"}, "from": {"id": chat_id, "username": username}, "text": f"/start {payload}"}})
    return r["text"] if isinstance(r, dict) else r      # ulangandan keyin javobda Mini App tugmasi ham bo'ladi


def _last_code(sent):
    import re
    return re.search(r"kodi: (\d{6})", sent[-1][1]).group(1)


def test_telegram_two_factor_flow(client, conn, tg):
    uid, _ = make_user(conn, "t_boss2", ["admin"])
    login(client, "t_boss2")
    assert client.get("/api/auth/me").json()["mfa_setup_required"] is True
    link = client.post("/api/auth/telegram/link").json()
    assert link["url"].startswith("https://t.me/aventos_test_bot?start=")
    payload = link["url"].split("start=")[1]
    assert "eskirgan" in _start(conn, 777001, "yolgon-kod")
    assert "ulandi" in _start(conn, 777001, payload)
    assert "eskirgan" in _start(conn, 777001, payload)                # bir martalik
    me = client.get("/api/auth/me").json()
    assert me["mfa_enabled"] is True and me["telegram_name"] == "@boss"
    stored = conn.execute(text("SELECT code_hash FROM telegram_code WHERE user_id = :u AND purpose = 'link'"), {"u": uid}).scalar()
    assert payload not in stored                                       # bazada faqat HMAC
    client.post("/api/auth/logout")
    # kirish: parol to'g'ri -> sessiya yo'q, kod Telegram'ga
    r = client.post("/api/auth/login", json={"login": "t_boss2", "password": TEST_PASSWORD})
    assert r.status_code == 200 and r.json()["mfa_required"] is True and "kp_session" not in r.cookies
    tok, code = r.json()["mfa_token"], _last_code(tg)
    assert tg[-1][0] == 777001
    assert client.post("/api/auth/mfa", json={"mfa_token": tok, "code": "000000" if code != "000000" else "111111"}).status_code == 401
    assert client.post("/api/auth/mfa/resend", json={"mfa_token": tok}).status_code == 429   # 30 soniya o'tmagan
    r = client.post("/api/auth/mfa", json={"mfa_token": tok, "code": code})
    assert r.status_code == 200 and r.json()["mfa_enabled"] is True
    assert "yangi kirish" in tg[-1][1]                                   # kirish haqida xabar
    assert client.post("/api/auth/mfa", json={"mfa_token": tok, "code": code}).status_code == 401   # kod bir martalik
    # uzish: parol + Telegram kodi
    client.post("/api/auth/telegram/unlink-code")
    ucode = _last_code(tg)
    assert client.post("/api/auth/telegram/unlink", json={"code": ucode, "password": "xato"}).status_code == 401
    assert client.post("/api/auth/telegram/unlink", json={"code": ucode, "password": TEST_PASSWORD}).status_code == 200
    assert client.get("/api/auth/me").json()["mfa_enabled"] is False


def test_telegram_code_attempts_limited(client, conn, tg):
    uid, _ = make_user(conn, "t_boss7", ["admin"])
    conn.execute(text("UPDATE app_user SET telegram_chat_id = 777002, telegram_linked_at = now() WHERE id = :u"), {"u": uid})
    r = client.post("/api/auth/login", json={"login": "t_boss7", "password": TEST_PASSWORD})
    tok, code = r.json()["mfa_token"], _last_code(tg)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/api/auth/mfa", json={"mfa_token": tok, "code": wrong})
    # 5 xatodan keyin to'g'ri kod ham ishlamaydi (kod yaroqsiz + login bloklangan)
    assert client.post("/api/auth/mfa", json={"mfa_token": tok, "code": code}).status_code in (401, 429)


def test_telegram_chat_cannot_link_two_users(client, conn, tg):
    a, _ = make_user(conn, "t_tg_a", ["manager"])
    conn.execute(text("UPDATE app_user SET telegram_chat_id = 777003, telegram_linked_at = now() WHERE id = :u"), {"u": a})
    make_user(conn, "t_tg_b", ["manager"])
    login(client, "t_tg_b")
    payload = client.post("/api/auth/telegram/link").json()["url"].split("start=")[1]
    assert "boshqa foydalanuvchiga" in _start(conn, 777003, payload)


def test_telegram_link_needs_bot(client, conn, monkeypatch):
    monkeypatch.setattr(telegram, "bot_username", lambda: None)
    make_user(conn, "t_sec", ["manager"])
    login(client, "t_sec")
    assert client.post("/api/auth/telegram/link").status_code == 503


def test_admin_revokes_sessions_and_deactivation(client, conn):
    make_user(conn, "t_boss3", ["admin"])
    uid, _ = make_user(conn, "t_sec", ["manager"])
    login(client, "t_sec")
    victim = client.cookies.get("kp_session")
    login(client, "t_boss3")
    assert client.post(f"/api/admin/users/{uid}/revoke-sessions").json()["revoked"] >= 1
    boss = client.cookies.get("kp_session")
    client.cookies.set("kp_session", victim)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set("kp_session", boss)
    ev = client.get("/api/admin/security-events", params={"event": "sessions_revoked"}).json()
    assert any(e["login"] == "t_sec" for e in ev["items"])


def test_join_link_bruteforce_blocked(client, conn):
    for i in range(10):
        assert client.get(f"/api/join/yolg'on-token-{i}").status_code == 404
    assert client.get("/api/join/yana-biri").status_code == 429


def test_security_headers(client):
    r = client.get("/api/health")
    h = r.headers
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "script-src 'self'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer" and h["cache-control"] == "no-store"


def test_zip_bomb_rejected(client, conn):
    make_user(conn, "t_boss4", ["admin"])
    login(client, "t_boss4")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"0" * (120 * 1024 * 1024))   # 120 MB, siqilgani ~120 KB
    r = client.post("/api/ahu-offers", files={"file": ("bomb.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 422 and "o'qib bo'lmadi" in r.json()["detail"]


def test_admin_word_required_for_admin_panel(client, conn):
    make_user(conn, "t_boss5", ["admin"])
    r = client.post("/api/auth/login", json={"login": "t_boss5", "password": TEST_PASSWORD})
    assert r.json()["admin_word_set"] is False
    r = client.get("/api/admin/users")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_word_setup"
    # parol bilan bir xil so'z — rad; noto'g'ri parol — rad
    assert client.post("/api/auth/admin-word/set", json={"password": TEST_PASSWORD, "word": TEST_PASSWORD}).status_code == 422
    assert client.post("/api/auth/admin-word/set", json={"password": "xato-parol", "word": "Yashil-olma-77"}).status_code == 401
    assert client.post("/api/auth/admin-word/set", json={"password": TEST_PASSWORD, "word": "Yashil-olma-77"}).json()["admin_unlocked"]
    assert client.get("/api/admin/users").status_code == 200
    stored = conn.execute(text("SELECT admin_word_hash FROM app_user WHERE login = 't_boss5'")).scalar()
    assert "Yashil" not in stored and stored.startswith("$argon2")
    # qulflash -> yana so'raladi; harakatsizlikdan keyin ham
    client.post("/api/auth/admin-word/lock")
    assert client.get("/api/admin/users").json()["detail"]["code"] == "admin_word_required"
    assert client.post("/api/auth/admin-word/verify", json={"word": "Yashil-olma-77"}).status_code == 200
    conn.execute(text("UPDATE user_session SET admin_unlocked_at = now() - interval '16 minutes' WHERE revoked_at IS NULL"))
    assert client.get("/api/admin/users").status_code == 403
    # almashtirish eski so'zsiz bo'lmaydi
    assert client.post("/api/auth/admin-word/set", json={"password": TEST_PASSWORD, "word": "Boshqa-soz-99"}).status_code == 401


def test_admin_word_bruteforce_logs_out(client, conn):
    make_user(conn, "t_boss6", ["admin"])
    login(client, "t_boss6")                                       # yordamchi so'zni o'rnatadi
    client.post("/api/auth/admin-word/lock")
    for _ in range(4):
        assert client.post("/api/auth/admin-word/verify", json={"word": "taxmin"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/admin-word/verify", json={"word": "taxmin"}).status_code == 401   # 5-xato
    assert client.get("/api/auth/me").status_code == 401                                          # chiqarib yuborildi
    login(client, "t_boss6")                                       # to'g'ri so'z ham — blok vaqtida ishlamaydi
    assert client.get("/api/admin/users").status_code == 403


def test_manager_cannot_set_admin_word(client, conn):
    make_user(conn, "t_sec", ["manager"])
    login(client, "t_sec")
    assert client.post("/api/auth/admin-word/set", json={"password": TEST_PASSWORD, "word": "Yashil-olma-77"}).status_code == 403


# ------------------------------------------------------------------ hujumdan himoya qatlami (shield.py, 2026-10-22)
def test_big_body_rejected_before_login(client):
    """Kirmagan odam ham katta tana yuborib server xotirasini to'ldira olmaydi — 413, tana o'qilmaydi."""
    r = client.post("/api/auth/login", content=b"x" * (2 * 1024 * 1024), headers={"content-type": "application/json"})
    assert r.status_code == 413
    r = client.post("/api/ahu-offers", files={"file": ("big.xlsx", b"0" * (12 * 1024 * 1024), "application/octet-stream")})
    assert r.status_code == 413


def test_rate_limit_per_ip(client, monkeypatch):
    from backend.app import shield
    monkeypatch.setitem(shield.LIMITS, "auth", 3)
    for _ in range(3):
        assert client.post("/api/auth/login", json={"login": "yoq_rl", "password": "x"}).status_code == 401
    r = client.post("/api/auth/login", json={"login": "yoq_rl", "password": "x"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert client.get("/api/health").status_code == 200              # umumiy API chegarasi alohida


def test_attack_alert_sent_to_admins(client, conn, monkeypatch):
    from backend.app import guard
    calls = []
    monkeypatch.setattr(guard, "alert_admins", lambda key, msg: calls.append(key))
    for i in range(20):
        client.post("/api/auth/login", json={"login": f"yoq_al{i}", "password": "x"})
    client.post("/api/auth/login", json={"login": "yoq_al", "password": "x"})
    assert any(k.startswith("ip_blocked:") for k in calls)
