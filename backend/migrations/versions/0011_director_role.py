"""Direktor roli: KP o'chirishdan (kp.delete) tashqari barcha ruxsatlar

SQL: sql/0011_director_role.sql

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0011_director_role.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DELETE FROM user_role WHERE role_code = 'director';"
                                  "DELETE FROM role_permission WHERE role_code = 'director';"
                                  "DELETE FROM role WHERE code = 'director';")
