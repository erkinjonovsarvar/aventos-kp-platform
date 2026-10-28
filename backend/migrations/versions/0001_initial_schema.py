"""Boshlang'ich sxema: 36 jadval, triggerlar, view'lar, ma'lumotnomalar

DATABASE_SCHEMA.md 5-versiya (2026-10-15 tasdiqlangan). SQL alohida faylda: sql/0001_initial_schema.sql

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0001_initial_schema.sql"


def upgrade() -> None:
    # Driverga to'g'ridan-to'g'ri (parametrsiz) beriladi — bir nechta buyruq bitta faylda
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    # Faqat bo'sh/sinov bazasi uchun. Ma'lumot bor bazada ishlatilmaydi.
    op.get_bind().exec_driver_sql(
        """
        DROP VIEW IF EXISTS v_active_user, v_user_effective_permission, v_price_list_check,
            v_project_discounts, v_quotation_totals, v_annex_totals, v_line_price CASCADE;
        DROP TABLE IF EXISTS data_issue, audit_log, annex_discount, quotation_line_custom,
            quotation_line_ahu_item, quotation_line_price_list, quotation_line, quotation_annex,
            quotation_revision, quotation, ahu_offer_item_tag, ahu_offer_item, ahu_offer, ahu_block,
            exchange_rate, vat_rate, price_list_item, price_list, product, source_document, project,
            product_series, brand, application_type, product_category, unit, currency,
            access_request, invitation, user_permission, role_permission, permission, user_role,
            app_user, role, employee CASCADE;
        DROP FUNCTION IF EXISTS trg_append_only, trg_price_list_item_lock, trg_price_list_lock,
            revision_is_locked, trg_revision_lock, revision_of_annex, revision_of_line,
            assert_revision_editable, trg_annex_lock, trg_by_annex_lock, trg_by_line_lock,
            trg_line_subtype_match, trg_line_has_detail, user_has_role, trg_discount_admin_only,
            trg_audit CASCADE;
        """
    )
