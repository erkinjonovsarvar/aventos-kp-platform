"""Baza ulanishi: har bir HTTP so'rov — bitta tranzaksiya (xato bo'lsa hammasi bekor qilinadi)."""
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection

from .config import settings

_engine = None


def engine():
    global _engine
    if _engine is None:
        s = settings()
        _engine = create_engine(
            URL.create("postgresql+psycopg", username=s.db_user, password=s.db_password,
                       host=s.db_host, port=s.db_port, database=s.db_name),
            pool_size=5, max_overflow=5, pool_pre_ping=True,
        )
    return _engine


def get_conn() -> Iterator[Connection]:
    """Har doim Depends(get_conn, scope="function") bilan ishlatiladi: tranzaksiya JAVOB YUBORILISHIDAN OLDIN
    yakunlanadi (commit). Aks holda brauzer javobni olib darhol so'ragan ma'lumot hali bazada bo'lmaydi
    (2026-10-15 xato: KP yaratilgach "KP topilmadi")."""
    with engine().connect() as conn:
        with conn.begin():
            yield conn


def set_actor(conn: Connection, user_id: int) -> None:
    """Audit jurnali uchun: shu tranzaksiyadagi o'zgarishlar kim nomidan."""
    conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


def plain(value):
    """JSON uchun: pul summalari aniqlik yo'qolmasligi uchun MATN sifatida (float emas)."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def rows(result) -> list[dict]:
    return [{k: plain(v) for k, v in r._mapping.items()} for r in result]


def row(result) -> dict | None:
    r = result.first()
    return None if r is None else {k: plain(v) for k, v in r._mapping.items()}
