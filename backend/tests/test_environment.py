"""Testlar ishlab turgan bazaga ulanmasligi kafolati (2026-10-20)."""
from sqlalchemy import text

from backend.app import db as app_db
from backend.app.config import settings


def test_settings_point_to_test_database():
    assert settings().db_name.endswith("_test"), settings().db_name


def test_app_engine_connects_to_test_database():
    with app_db.engine().connect() as c:
        assert c.execute(text("SELECT current_database()")).scalar_one().endswith("_test")


def test_fixture_connection_is_test_database(db):
    assert db.execute("SELECT current_database()").fetchone()[0].endswith("_test")


def test_telegram_disabled_in_tests():
    assert settings().telegram_bot_token == "", "test muhitida haqiqiy Telegram xabarlari ketmasligi kerak"
