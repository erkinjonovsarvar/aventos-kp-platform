"""KP savdo holati: deal_status, lost_reason, quotation_deal_event (tarix), v_quotation_deal; deal.update va dashboard.view ruxsatlari

SQL: sql/0015_deal_status.sql

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-16
"""
from pathlib import Path

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0015_deal_status.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    sql9 = (Path(__file__).resolve().parents[1] / "sql" / "0009_admin_delete_quotation.sql").read_text(encoding="utf-8")
    fn = sql9[sql9.index("CREATE FUNCTION delete_quotation"):sql9.index("REVOKE ALL")].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    op.get_bind().exec_driver_sql(
        "DROP VIEW v_quotation_deal; DROP TABLE quotation_deal_event; DROP FUNCTION trg_deal_event_append_only();"
        "DROP TABLE lost_reason; DROP TABLE deal_status;"
        "DELETE FROM user_permission WHERE permission_code IN ('deal.update', 'dashboard.view');"
        "DELETE FROM role_permission WHERE permission_code IN ('deal.update', 'dashboard.view');"
        "DELETE FROM permission WHERE code IN ('deal.update', 'dashboard.view');" + fn)
