"""Admin har qanday KP ni (tasdiqlangan/yuborilgan ham) butunlay o'chiradi: delete_quotation() SECURITY DEFINER

SQL: sql/0009_admin_delete_quotation.sql

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0009_admin_delete_quotation.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("0009 ni orqaga qaytarish ko'zda tutilmagan")
