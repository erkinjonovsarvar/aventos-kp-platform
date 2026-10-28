"""AHU tavsifi: VRF/AHU kit bo'lsa "с ККБ и AHU kit" qo'shiladi

SQL: sql/0012_ahu_vrf_description.sql

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-16
"""
from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0012_ahu_vrf_description.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    sql7 = (Path(__file__).resolve().parents[1] / "sql" / "0007_price_line_category.sql").read_text(encoding="utf-8")
    views = sql7[sql7.index("CREATE VIEW v_line_price"):]
    op.get_bind().exec_driver_sql("DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price, "
                                  "v_price_list_check;" + views)
