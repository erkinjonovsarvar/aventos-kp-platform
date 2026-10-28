"""Regressiya: tranzaksiya JAVOB YUBORILISHIDAN OLDIN yakunlanishi kerak.
2026-10-15 xato: KP yaratildi, brauzer darhol so'radi — hali commit bo'lmagani uchun "KP topilmadi" (404)."""
import asyncio
import re
from pathlib import Path

from fastapi import Depends, FastAPI

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_every_get_conn_dependency_commits_before_response():
    bad = []
    for f in APP_DIR.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"Depends\(get_conn[^)]*\)", line):
                if 'scope="function"' not in m.group(0):
                    bad.append(f"{f.name}:{n}")
    assert not bad, f"scope=\"function\" yo'q: {bad}"


def test_function_scope_finishes_before_response_start():
    """FastAPI kafolati: scope="function" li yield-dependency javob boshlanishidan oldin yopiladi."""
    events = []

    def dep():
        yield "conn"
        events.append("commit")

    app = FastAPI()

    @app.post("/x")
    def endpoint(c=Depends(dep, scope="function")):
        return {"ok": True}

    async def run():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                events.append("response")

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "path": "/x",
                 "raw_path": b"/x", "query_string": b"", "headers": [], "scheme": "http", "server": ("t", 80),
                 "client": ("t", 1), "root_path": ""}
        await app(scope, receive, send)

    asyncio.run(run())
    assert events == ["commit", "response"]
