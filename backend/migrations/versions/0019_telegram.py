"""2 bosqichli kirish Telegram orqali: app_user.telegram_*, telegram_code; TOTP ustunlari olib tashlandi

SQL: sql/0019_telegram.sql

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-17
"""
from pathlib import Path

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0019_telegram.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DROP TABLE telegram_code;"
        "ALTER TABLE app_user DROP CONSTRAINT app_user_telegram_check, DROP COLUMN telegram_linked_at,"
        " DROP COLUMN telegram_name, DROP COLUMN telegram_chat_id;"
        "ALTER TABLE app_user ADD COLUMN totp_secret_enc text, ADD COLUMN totp_enabled_at timestamptz,"
        " ADD CONSTRAINT app_user_totp_check CHECK (totp_enabled_at IS NULL OR totp_secret_enc IS NOT NULL);")
