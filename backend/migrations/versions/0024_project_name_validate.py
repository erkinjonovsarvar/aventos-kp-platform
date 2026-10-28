"""Loyiha nomi bo'sh bo'lmasligi cheklovi to'liq (VALID) — C011 dan keyin

Bazada bo'sh nomli loyiha qolgan bo'lsa, migratsiya xato beradi va hech narsa o'zgarmaydi (avval C011 bajarilishi kerak).

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-20
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE project VALIDATE CONSTRAINT project_name_not_blank;")


def downgrade() -> None:
    # VALID holatni NOT VALID ga qaytarish: cheklovni qayta yaratish (0022 dagidek)
    op.get_bind().exec_driver_sql(
        "ALTER TABLE project DROP CONSTRAINT project_name_not_blank;"
        "ALTER TABLE project ADD CONSTRAINT project_name_not_blank CHECK (btrim(name) <> '') NOT VALID;")
