"""Narxlar cheklovsiz aniqlikda (numeric) — Excel'dagi teskari hisoblangan narxlar uchun

SQL: sql/0004_full_precision_prices.sql

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0004_full_precision_prices.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("0004 ni orqaga qaytarish ko'zda tutilmagan (aniqlik yo'qolishi mumkin)")
