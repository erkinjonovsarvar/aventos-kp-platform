"""Menejer roli KP ni Excel/PDF qilib yuklab ola olmaydi (kp.download roldan olinadi) — hozircha

SQL: sql/0027_manager_no_download.sql

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-28
"""
from pathlib import Path

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / "0027_manager_no_download.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "INSERT INTO role_permission (role_code, permission_code) VALUES ('manager', 'kp.download') ON CONFLICT DO NOTHING")
