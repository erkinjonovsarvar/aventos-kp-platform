"""Narx ro'yxati qatorining KP dagi kategoriyasi (quotation_line_price_list.category_id)

SQL: sql/0007_price_line_category.sql

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0007_price_line_category.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("0007 ni orqaga qaytarish ko'zda tutilmagan")
