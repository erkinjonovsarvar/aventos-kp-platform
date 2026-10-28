"""Eski KP importi uchun: to'liq aniqlikdagi narxlar, bo'sh qiymatlarga ruxsat, NULL-xavfsiz jamlar

SQL: sql/0002_legacy_import_precision.sql

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0002_legacy_import_precision.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("0002 ni orqaga qaytarish ko'zda tutilmagan (ma'lumot yo'qolishi mumkin)")
