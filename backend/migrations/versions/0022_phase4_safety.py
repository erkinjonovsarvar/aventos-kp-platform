"""Phase 4: audit jurnalida maxfiy hash'lar yo'q, login lower() bo'yicha yagona, bo'sh nomlar taqiqlangan

SQL: sql/0022_phase4_safety.sql

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-20
"""
from pathlib import Path

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0022_phase4_safety.sql"

# 0021 gacha amalda bo'lgan trg_audit (faqat password_hash olib tashlanardi)
OLD_TRG_AUDIT = """
CREATE OR REPLACE FUNCTION trg_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_user bigint := nullif(current_setting('app.user_id', true), '')::bigint;
    v_old jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
    v_new jsonb := CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN to_jsonb(NEW) END;
    v_key text;
BEGIN
    -- parol hash'lari jurnalga yozilmaydi
    v_old := v_old - 'password_hash';
    v_new := v_new - 'password_hash';
    v_key := coalesce(v_new, v_old) ->> 'id';
    IF v_key IS NULL THEN
        v_key := coalesce(coalesce(v_new, v_old) ->> 'line_id', coalesce(v_new, v_old) ->> 'annex_id',
                          coalesce(v_new, v_old) ->> 'user_id');
    END IF;
    INSERT INTO audit_log (user_id, table_name, record_id, action, old_data, new_data)
    VALUES (v_user, TG_TABLE_NAME, coalesce(v_key, '?'), lower(TG_OP), v_old, v_new);
    RETURN NULL;
END $$;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE quotation_annex DROP CONSTRAINT quotation_annex_name_not_blank;"
        "ALTER TABLE project DROP CONSTRAINT project_name_not_blank;"
        "DROP INDEX app_user_login_lower_key;" + OLD_TRG_AUDIT)
