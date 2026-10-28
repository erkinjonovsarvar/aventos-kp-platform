"""Audit jurnali qo'shimcha jadvallarda (ilova, xodim, loyiha, kategoriya, mahsulot, narx qatori ...)

SQL: sql/0005_more_audit.sql

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0005_more_audit.sql"
TABLES = ("quotation_annex", "employee", "project", "product_category", "product", "price_list_item",
          "quotation_line_price_list", "quotation_line_ahu_item", "invitation")


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("".join(f"DROP TRIGGER audit ON {t};" for t in TABLES))
