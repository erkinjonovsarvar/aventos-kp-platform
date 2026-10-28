"""Alembic muhiti: migratsiyalar jadvallar egasi (aventos_owner) nomidan bajariladi.
KP_ENV_FILE berilsa — o'sha fayl (masalan .env.test -> aventos_kp_test), aks holda .env (asosiy baza)."""
import os
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

ENV_FILE = Path(os.environ["KP_ENV_FILE"]) if os.environ.get("KP_ENV_FILE") else Path(__file__).resolve().parents[2] / ".env"


def owner_url() -> URL:
    cfg = dotenv_values(ENV_FILE)
    return URL.create(
        "postgresql+psycopg",
        username=cfg["DB_OWNER_USER"],
        password=cfg["DB_OWNER_PASSWORD"],
        host=cfg["DB_HOST"],
        port=int(cfg["DB_PORT"]),
        database=cfg["DB_NAME"],
    )


def run_migrations_online() -> None:
    engine = create_engine(owner_url())
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline rejim ishlatilmaydi")
run_migrations_online()
