"""Tayyor (tasdiqlangan/yuborilgan) KP ning valyutasini (USD <-> UZS) shu revisionda almashtirish, tarix bilan

SQL: sql/0028_kp_currency_change.sql

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-28
"""
from pathlib import Path

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql((SQL_DIR / "0028_kp_currency_change.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    s09 = (SQL_DIR / "0009_admin_delete_quotation.sql").read_text(encoding="utf-8")
    fn = s09[s09.index("CREATE OR REPLACE FUNCTION trg_revision_lock"):]
    fn = fn[:fn.index("END $$;") + len("END $$;")]
    op.get_bind().exec_driver_sql(
        fn + "DROP FUNCTION change_revision_currency(bigint, text, bigint);"
        "DROP TABLE revision_currency_change; DROP FUNCTION trg_currency_change_append_only();"
        "DROP FUNCTION kp_currency_change_in_progress(bigint);")
