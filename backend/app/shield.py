"""Hujumdan himoya qatlami (2026-10-22, foydalanuvchi: "kiberhujum kutilmoqda"): so'rov hajmi va soni cheklovi.

- So'rov tanasi hajmi: kirish tekshirilishidan OLDIN ham (FastAPI tanani avval o'qiydi) — begona odam katta fayl yuborib
  server xotirasi/diskini to'ldira olmasin. AHU fayl yuklash — 11 MB, qolgan hammasi — 1 MB.
- IP bo'yicha so'rovlar soni (xotirada, 1 daqiqalik oyna): kirish/kod/taklif havolasi — 30, API — 600. Oshsa 429.
  Parol taxminini bazadagi blok (guard.py) to'xtatadi; bu qatlam esa serverni so'rov oqimi bilan bo'g'ishni to'xtatadi.
- Cheklovga tushgan IP haqida adminlarga Telegram xabari (guard.alert_admins, 15 daqiqada bir marta).
"""
import json
import re
import time
from collections import deque

from starlette.requests import Request

from . import guard

MB = 1024 * 1024
BODY_LIMITS = {"/api/ahu-offers": 11 * MB}         # kp_edit.MAX_UPLOAD (10 MB) + multipart sarlavhalari
EVIDENCE_PATH = re.compile(r"^/api/quotations/\d+/evidence$")   # chegirma isboti (evidence.MAX_BYTES 10 MB)
BODY_DEFAULT = 1 * MB
STRICT_PREFIXES = ("/api/auth/login", "/api/auth/mfa", "/api/auth/telegram/webapp", "/api/join/")
LIMITS = {"auth": 30, "api": 600}                 # bitta IP dan 1 daqiqada
WINDOW = 60.0

_hits: dict[tuple[str, str], deque] = {}
_last_prune = 0.0


def reset() -> None:
    """Testlar uchun: hisoblagichlarni tozalash."""
    _hits.clear()


def _limited(bucket: str, ip: str, now: float) -> bool:
    global _last_prune
    if now - _last_prune > WINDOW:                 # eski yozuvlar xotirada to'planmasin
        for k in [k for k, q in _hits.items() if not q or q[-1] < now - WINDOW]:
            del _hits[k]
        _last_prune = now
    q = _hits.setdefault((bucket, ip), deque())
    while q and q[0] < now - WINDOW:
        q.popleft()
    if len(q) >= LIMITS[bucket]:
        return True
    q.append(now)
    return False


async def _send_json(send, code: int, detail: str, headers: list[tuple[bytes, bytes]] = ()) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": code,
                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store"), *headers]})
    await send({"type": "http.response.body", "body": body})


class Shield:
    """ASGI middleware (eng tashqi qatlam — boshqa hamma narsadan oldin ishlaydi)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path.startswith("/api/"):
            ip = guard.client_ip(Request(scope))
            bucket = "auth" if path.startswith(STRICT_PREFIXES) else "api"
            if _limited(bucket, ip, time.monotonic()):
                guard.alert_admins(f"rate:{bucket}:{ip}",
                                   f"⚠️ AVENTOS KP: {ip} IP dan juda ko'p so'rov ({bucket}, >{LIMITS[bucket]}/daqiqa) — "
                                   "vaqtincha cheklandi. Hujum bo'lishi mumkin.")
                return await _send_json(send, 429, "Juda ko'p so'rov — bir daqiqadan keyin qayta urining",
                                        [(b"retry-after", b"60")])

        limit = BODY_LIMITS.get(path, 11 * MB if EVIDENCE_PATH.match(path) else BODY_DEFAULT)
        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None:
            try:
                too_big = int(length) > limit
            except ValueError:
                return await _send_json(send, 400, "Content-Length noto'g'ri")
            if too_big:
                return await _send_json(send, 413, f"So'rov juda katta (chegara {limit // MB} MB)")

        received = 0

        async def limited_receive():
            # Content-Length siz (chunked) so'rov: chegaradan oshsa — ulanish uzilgan deb hisoblanadi
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    return {"type": "http.disconnect"}
            return message

        return await self.app(scope, limited_receive, send)
