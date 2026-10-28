"""Valve ro'yxati AHU tavsifidan 1 bo'sh qator bilan (16.10.2026 16:30 dan keyingi revisionlar)

SQL: sql/0014_valve_one_blank_line.sql

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-16
"""
from pathlib import Path

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0014_valve_one_blank_line.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    sql7 = (Path(__file__).resolve().parents[1] / "sql" / "0013_ahu_kkb_by_kp_lines.sql").read_text(encoding="utf-8")
    views = sql7[sql7.index("CREATE VIEW v_line_price"):]
    op.get_bind().exec_driver_sql("DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price, "
                                  "v_price_list_check;" + views)
