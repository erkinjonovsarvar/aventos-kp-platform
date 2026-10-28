"""3-way valve qatorida quvvat (kg/h) ko'rsatilmaydi; avval tasdiqlangan KP lar o'zgarmaydi

SQL: sql/0026_valve_no_capacity.sql

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-28
"""
from pathlib import Path

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / "0026_valve_no_capacity.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    s25 = (SQL_DIR / "0025_line_discount.sql").read_text(encoding="utf-8")
    view = s25[s25.index("CREATE VIEW v_line_price AS"):]
    view = view[:view.index(") z;") + len(") z;")]
    op.get_bind().exec_driver_sql(view.replace("CREATE VIEW", "CREATE OR REPLACE VIEW", 1))
