"""AHU narxlari har doim ROUNDUP (QQS bilan, butun songa yuqoriga)

SQL: sql/0021_ahu_roundup.sql

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-17
"""
from pathlib import Path

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / "0021_ahu_roundup.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    sql16 = (SQL_DIR / "0016_discount_full_precision.sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql("DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price, v_price_list_check;"
                                  + sql16[sql16.index("CREATE VIEW v_line_price"):])
