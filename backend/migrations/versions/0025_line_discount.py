"""Mahsulot (qator) chegirmasi va chegirma isboti (skrinshot/PDF)

SQL: sql/0025_line_discount.sql

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-22
"""
from pathlib import Path

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / "0025_line_discount.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    s21 = (SQL_DIR / "0021_ahu_roundup.sql").read_text(encoding="utf-8")
    views = s21[s21.index("CREATE VIEW v_line_price AS"):s21.index("-- Narx ro'yxati: QQS bilan narx qoidaga")]
    s15 = (SQL_DIR / "0015_deal_status.sql").read_text(encoding="utf-8")
    fn = s15[s15.index("CREATE OR REPLACE FUNCTION delete_quotation"):]
    fn = fn[:fn.index("END $$;") + len("END $$;")]
    op.get_bind().exec_driver_sql(
        "DROP VIEW v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price;"
        + views + fn +
        "DROP TABLE discount_evidence_link; DROP TABLE discount_evidence; DROP FUNCTION trg_evidence_append_only();"
        "DROP TABLE line_discount;")
