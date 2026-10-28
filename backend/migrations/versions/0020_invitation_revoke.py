"""Taklif havolasini bekor qilish: invitation.revoked_at

SQL: sql/0020_invitation_revoke.sql

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-17
"""
from pathlib import Path

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0020_invitation_revoke.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE invitation DROP COLUMN revoked_at;")
