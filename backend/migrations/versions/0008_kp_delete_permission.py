"""KP ni o'chirish — alohida ruxsat (kp.delete), faqat admin rolida

SQL: sql/0008_kp_delete_permission.sql

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0008_kp_delete_permission.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DELETE FROM user_permission WHERE permission_code = 'kp.delete';"
        "DELETE FROM role_permission WHERE permission_code = 'kp.delete';"
        "DELETE FROM permission WHERE code = 'kp.delete';")
