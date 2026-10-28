"""KP yaratish (AHU fayldan): unit_label, ahu_block ma'lumotnomasi, v_line_price yangilanishi

SQL: sql/0006_ahu_kp_creation.sql

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0006_ahu_kp_creation.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("0006 ni orqaga qaytarish ko'zda tutilmagan")
