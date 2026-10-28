"""Bo'shatilgan KP raqamlari (kp_number_release)

SQL: sql/0010_kp_number_release.sql

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0010_kp_number_release.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE kp_number_release;")
