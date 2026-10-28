"""Migratsiya 0022 va sessiya tozalash (2026-10-20). Har test ROLLBACK."""
import psycopg
import pytest
from sqlalchemy import text

from .test_api import client, conn, login, make_user  # noqa: F401  (pytest fixture'lari)


def test_alembic_head_is_0022(db):
    assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] in ("0022", "0023", "0024", "0025", "0026", "0027", "0028")


def test_audit_log_has_no_secret_hashes(b):
    uid = b.admin
    b.con.execute("UPDATE app_user SET admin_word_hash = 'sir-hash', password_hash = 'p-hash' WHERE id = %s", (uid,))
    old, new = b.con.execute(
        """SELECT old_data, new_data FROM audit_log WHERE table_name = 'app_user' AND record_id = %s
           ORDER BY id DESC LIMIT 1""", (str(uid),)).fetchone()
    for d in (old, new):
        assert "admin_word_hash" not in d and "password_hash" not in d
    assert new["login"] == "test_admin_t"                       # qolgan ma'lumot jurnalda bor


def test_login_unique_case_insensitive(b):
    emp = b.one("INSERT INTO employee (full_name) VALUES ('Katta harf') RETURNING id")
    with pytest.raises(psycopg.errors.UniqueViolation):
        b.con.execute("INSERT INTO app_user (employee_id, login, password_hash) VALUES (%s, 'TEST_ADMIN_T', 'x')", (emp,))


def test_blank_project_and_annex_names_rejected(b):
    with pytest.raises(psycopg.errors.CheckViolation):
        b.con.execute("INSERT INTO project (project_no, name) VALUES (999902, '   ')")


def test_blank_annex_name_rejected(b):
    rev = b.revision()
    with pytest.raises(psycopg.errors.CheckViolation):
        b.annex(rev, 1, "  ")


def test_blank_projects_state_matches_migration(db):
    """0022: cheklov NOT VALID — eski 17 ta bo'sh nomli loyiha qoladi; C011 (foydalanuvchi qarori) ularni o'chiradi,
    0024 cheklovni VALID qiladi. Ikkala holat ham izchil bo'lishi kerak."""
    n = db.execute("SELECT count(*) FROM project WHERE btrim(name) = ''").fetchone()[0]
    valid = db.execute("SELECT convalidated FROM pg_constraint WHERE conname = 'project_name_not_blank'").fetchone()[0]
    assert (n == 0 and valid) or (n == 17 and not valid), (n, valid)


def test_login_expires_stale_sessions(client, conn):
    uid, _ = make_user(conn, "t_sess", ["manager"])
    conn.execute(text("""INSERT INTO user_session (user_id, token_hash, created_at, last_seen_at, expires_at)
                         VALUES (:u, repeat('a', 64), now() - interval '10 hours', now() - interval '9 hours',
                                 now() - interval '1 hour')"""), {"u": uid})
    assert login(client, "t_sess").status_code == 200
    reason = conn.execute(text("SELECT revoked_reason FROM user_session WHERE token_hash = repeat('a', 64)")).scalar_one()
    assert reason == "expired"
    active = conn.execute(text("SELECT count(*) FROM user_session WHERE user_id = :u AND revoked_at IS NULL"), {"u": uid}).scalar_one()
    assert active == 1                                          # yangi kirish sessiyasi


def test_0023_derived_excl_price_is_ok(b):
    """0023: QQSsiz narx QQS bilan narxdan hisoblangan bo'lsa (QQS bilan / 1,12, yaxlitlanmagan) — OK; buzilgan narx — TEKSHIRISH KERAK."""
    if b.con.execute("SELECT version_num FROM alembic_version").fetchone()[0] < "0023":
        pytest.skip("0023 qo'llanmagan")
    pl = b.one("INSERT INTO price_list (name, valid_from, source_document_id) VALUES ('t', '2000-01-02', %s) RETURNING id", b.doc)
    ser = b.one("INSERT INTO product_series (brand_id, name) VALUES ((SELECT min(id) FROM brand), 'T seriya') RETURNING id")
    ok_p = b.one("INSERT INTO product (model, series_id) VALUES ('T-DERIVED', %s) RETURNING id", ser)
    bad_p = b.one("INSERT INTO product (model, series_id) VALUES ('T-BROKEN', %s) RETURNING id", ser)
    for p, ex, inc in ((ok_p, "157 / 1.12", 157), (bad_p, "150", 157)):
        b.con.execute(f"""INSERT INTO price_list_item (price_list_id, product_id, currency_code, price_excl_vat, price_incl_vat, source_row)
                          VALUES (%s, %s, 'USD', {ex}, %s, 1)""", (pl, p, inc))
    got = dict(b.con.execute("""SELECT model, check_status FROM v_price_list_check c JOIN price_list_item i ON i.id = c.price_list_item_id
                                WHERE i.price_list_id = %s""", (pl,)).fetchall())
    assert got == {"T-DERIVED": "OK", "T-BROKEN": "TEKSHIRISH KERAK"}
