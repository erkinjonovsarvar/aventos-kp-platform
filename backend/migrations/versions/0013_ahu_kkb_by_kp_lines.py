"""AHU tavsifi oxiri KP qatorlariga qarab: VRF -> "с ККБ и AHU kit", faqat kit -> "с AHU kit"

SQL: sql/0013_ahu_kkb_by_kp_lines.sql

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-16
"""
from pathlib import Path

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0013_ahu_kkb_by_kp_lines.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    sql7 = (Path(__file__).resolve().parents[1] / "sql" / "0012_ahu_vrf_description.sql").read_text(encoding="utf-8")
    views = sql7[sql7.index("CREATE VIEW v_line_price"):]
    op.get_bind().exec_driver_sql("DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price, "
                                  "v_price_list_check;" + views)
