"""Test muhiti: har bir test dastur foydalanuvchisi (aventos_app) nomidan, alohida tranzaksiyada
ishlaydi va oxirida ROLLBACK qilinadi — bazada hech narsa qolmaydi.

Testlar FAQAT alohida test bazasiga ulanadi (2026-10-20): sozlama D:/KP_AGENT/.env.test dan
(yoki KP_ENV_FILE dan) olinadi; baza nomi "_test" bilan tugamasa — testlar umuman boshlanmaydi."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("KP_ENV_FILE", str(ROOT / ".env.test"))   # backend.app import qilinishidan OLDIN

import psycopg  # noqa: E402
import pytest  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

ENV_PATH = Path(os.environ["KP_ENV_FILE"])
if not ENV_PATH.is_file():
    pytest.exit(f"Test sozlamasi topilmadi: {ENV_PATH} (asosiy .env testlar uchun ishlatilmaydi)", returncode=2)
ENV = dotenv_values(ENV_PATH)
if not (ENV.get("DB_NAME") or "").endswith("_test"):
    pytest.exit(f"Testlar faqat '_test' bilan tugaydigan bazada ishlaydi (hozir: {ENV.get('DB_NAME')!r})", returncode=2)
if os.environ.get("DB_NAME") and not os.environ["DB_NAME"].endswith("_test"):
    pytest.exit("DB_NAME muhit o'zgaruvchisi asosiy bazaga ko'rsatmoqda — testlar to'xtatildi", returncode=2)


@pytest.fixture
def db():
    con = psycopg.connect(
        host=ENV["DB_HOST"], port=ENV["DB_PORT"], dbname=ENV["DB_NAME"],
        user=ENV["DB_USER"], password=ENV["DB_PASSWORD"],
    )
    try:
        yield con
    finally:
        con.rollback()
        con.close()


class Builder:
    """Sinov ma'lumotlarini yaratish uchun yordamchi."""

    def __init__(self, con):
        self.con = con

    def one(self, sql, *params):
        return self.con.execute(sql, params).fetchone()[0]

    def user(self, name, *roles):
        emp = self.one("INSERT INTO employee (full_name) VALUES (%s) RETURNING id", name)
        uid = self.one(
            "INSERT INTO app_user (employee_id, login, password_hash) VALUES (%s, %s, 'x') RETURNING id",
            emp, f"test_{name}",
        )
        for r in roles:
            self.con.execute("INSERT INTO user_role (user_id, role_code) VALUES (%s, %s)", (uid, r))
        return uid, emp

    def basics(self):
        self.admin, self.admin_emp = self.user("admin_t", "admin")
        self.vat = self.one(
            "INSERT INTO vat_rate (rate, valid_from, source, approved_by) VALUES (0.12, '2000-01-01', 'test', %s) RETURNING id",
            self.admin,
        )
        self.project = self.one("INSERT INTO project (project_no, name) VALUES (999901, 'Test loyiha') RETURNING id")
        self.cat_ahu = self.one("INSERT INTO product_category (name) VALUES ('AHU_t') RETURNING id")
        self.cat_acc = self.one("INSERT INTO product_category (name) VALUES ('Аксесуары_t') RETURNING id")
        for code, cat in [("AHU", self.cat_ahu), ("AUTOMATION", self.cat_ahu), ("VALVE", self.cat_acc)]:
            # 0006 dan boshlab ma'lumotnoma bazada bor — bo'lmasa (bo'sh bazada) qo'shiladi
            self.con.execute("INSERT INTO ahu_block (code, category_id) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING", (code, cat))
        self.doc = self.one(
            "INSERT INTO source_document (file_name, sha256, kind, uploaded_by) VALUES ('t.xlsx', %s, 'ahu_offer', %s) RETURNING id",
            "A" * 64, self.admin,
        )
        return self

    def revision(self, kp_number=999000001, currency="USD", rate_id=None):
        q = self.one(
            "INSERT INTO quotation (kp_number, project_id, manager_id, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
            kp_number, self.project, self.admin_emp, self.admin,
        )
        return self.one(
            """INSERT INTO quotation_revision (quotation_id, revision_no, kp_date, display_currency, exchange_rate_id, vat_rate_id)
               VALUES (%s, 1, '2026-10-15', %s, %s, %s) RETURNING id""",
            q, currency, rate_id, self.vat,
        )

    def annex(self, revision_id, no=1, name="AHU"):
        return self.one(
            "INSERT INTO quotation_annex (revision_id, annex_no, name) VALUES (%s, %s, %s) RETURNING id",
            revision_id, no, name,
        )

    def line(self, annex_id, no, line_type, qty=1, margin=None):
        return self.one(
            """INSERT INTO quotation_line (annex_id, line_no, line_type, quantity, unit_code, margin_pct)
               VALUES (%s, %s, %s, %s, 'шт', %s) RETURNING id""",
            annex_id, no, line_type, qty, margin,
        )

    def custom_line(self, annex_id, no, price, qty=1, incl_override=None):
        lid = self.line(annex_id, no, "custom", qty)
        self.con.execute(
            """INSERT INTO quotation_line_custom (line_id, description, unit_price_excl_vat, price_incl_vat_override, currency_code)
               VALUES (%s, 'Test qator', %s, %s, 'USD')""",
            (lid, price, incl_override),
        )
        return lid

    def offer(self):
        return self.one(
            "INSERT INTO ahu_offer (source_document_id, currency_code) VALUES (%s, 'USD') RETURNING id", self.doc
        )

    def item(self, offer, row, block, price, qty=1, parent=None, model=None, description=None, air_flow=None,
             flow_kg_h=None, unit_label=None):
        return self.one(
            """INSERT INTO ahu_offer_item (ahu_offer_id, source_row, block_code, parent_item_id, model, description,
                                           air_flow, flow_kg_h, quantity, unit_price, unit_label)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            offer, row, block, parent, model, description, air_flow, flow_kg_h, qty, price, unit_label,
        )

    def link(self, line_id, item_id, include=True):
        self.con.execute(
            "INSERT INTO quotation_line_ahu_item (line_id, ahu_offer_item_id, include_in_price) VALUES (%s, %s, %s)",
            (line_id, item_id, include),
        )

    def check_deferred(self):
        self.con.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.fixture
def b(db):
    return Builder(db).basics()
