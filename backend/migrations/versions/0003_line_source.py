"""Import qilingan KP qatorining manbasi (source_document + qator raqami)

SQL: sql/0003_line_source.sql

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0003_line_source.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE quotation_line_custom DROP CONSTRAINT quotation_line_custom_source_pair, "
        "DROP COLUMN source_row, DROP COLUMN source_document_id;"
    )
