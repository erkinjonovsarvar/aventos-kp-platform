"""Xavfsizlik: user_session (bazadagi sessiyalar), auth_event (jurnal), app_user.totp_* (2FA)

SQL: sql/0017_security.sql

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-17
"""
from pathlib import Path

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0017_security.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE app_user DROP CONSTRAINT app_user_totp_check, DROP COLUMN totp_enabled_at, DROP COLUMN totp_secret_enc;"
        "DROP TABLE auth_event; DROP FUNCTION trg_auth_event_append_only(); DROP TABLE user_session;")
