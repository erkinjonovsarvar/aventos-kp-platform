"""Narx ro'yxati QQS tekshiruvi: QQS bilan narxdan hisoblangan QQSsiz narx ham OK; is_current ustuni

SQL: sql/0023_price_check_derived.sql

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-20
"""
from pathlib import Path

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / "0023_price_check_derived.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    sql21 = (SQL_DIR / "0021_ahu_roundup.sql").read_text(encoding="utf-8")
    # is_current ustuni olib tashlanadi — CREATE OR REPLACE bilan bo'lmaydi, view qayta yaratiladi (unga bog'liq obyekt yo'q)
    op.get_bind().exec_driver_sql("DROP VIEW v_price_list_check;" + sql21[sql21.index("CREATE VIEW v_price_list_check"):])
