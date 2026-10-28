"""Admin paneli uchun maxfiy so'z: app_user.admin_word_*, user_session.admin_unlocked_at, yangi jurnal hodisalari

SQL: sql/0018_admin_word.sql

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-17
"""
from pathlib import Path

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0018_admin_word.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE user_session DROP COLUMN admin_unlocked_at;"
        "ALTER TABLE app_user DROP COLUMN admin_word_set_at, DROP COLUMN admin_word_hash;")
