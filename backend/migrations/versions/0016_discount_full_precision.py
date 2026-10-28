"""Ilova chegirmasi foizi to'liq aniqlikda (numeric(6,4) -> numeric)

SQL: sql/0016_discount_full_precision.sql

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-16
"""
from pathlib import Path

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0016_discount_full_precision.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    sql14 = (Path(__file__).resolve().parents[1] / "sql" / "0014_valve_one_blank_line.sql").read_text(encoding="utf-8")
    views = sql14[sql14.index("CREATE VIEW v_line_price"):]
    op.get_bind().exec_driver_sql("DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price, v_price_list_check;"
                                  "ALTER TABLE annex_discount ALTER COLUMN discount_pct TYPE numeric(6,4);" + views)
