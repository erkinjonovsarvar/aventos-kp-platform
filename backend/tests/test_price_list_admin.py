"""Narx ro'yxatini platformada yangilash (2026-10-22). Har test ROLLBACK — test bazasida hech narsa qolmaydi."""
from decimal import Decimal

from sqlalchemy import text

from backend.app import kp_service as svc
from backend.app import price_admin as P
from .test_api import client, conn, login, make_user  # noqa: F401  (pytest fixture'lari)


def _existing(conn):
    """Joriy katalogdan QQS qoidasiga mos bitta model."""
    return conn.execute(text(
        """SELECT p.model, i.price_excl_vat, i.price_incl_vat, i.description FROM price_list_item i
           JOIN price_list pl ON pl.id = i.price_list_id JOIN product p ON p.id = i.product_id
           JOIN v_price_list_check c ON c.price_list_item_id = i.id
           WHERE c.is_current AND c.check_status = 'OK' AND i.description IS NOT NULL ORDER BY p.model LIMIT 1""")).mappings().one()


def test_parse_header_and_layouts():
    p = P.parse("Hisense Model\tНаименование\tCapacity (KW)\tkw or m3/h\tЦена продажи без НДС\tЦена продажи с НДС\n"
                "NEW-1\tRekuperator\t1000\tm3/h\t1300\t1456\n\n")
    assert p["header"] and p["columns"] == {"price_excl_vat": 4, "price_incl_vat": 5, "model": 0, "unit": 3,
                                            "capacity": 2, "description": 1}
    assert p["items"] == [{"row": 2, "model": "NEW-1", "description": "Rekuperator", "capacity": "1000", "unit": "m3/h",
                           "brand": None, "series": None, "price_excl_vat": "1300", "price_incl_vat": "1456"}]
    # Original DB 'DB 16.05.2026' qatorlari sarlavhasiz (A–K)
    o = P.parse("\tAVENTOS\t1000\tm3/h\t\t\tHRV 1000\t\tРекуператор\t1 300,00\t1 456")
    assert not o["header"] and "Original DB" in o["layout"]
    assert (o["items"][0]["model"], o["items"][0]["brand"], o["items"][0]["price_incl_vat"]) == ("HRV 1000", "AVENTOS", "1 456")
    # Price database 'DATABASE PRICE' (A–H)
    t = P.parse("S\tHisense\t22.4\tkw\tX-1\tVRF\t3990\t4469")
    assert "Price database" in t["layout"] and t["items"][0]["model"] == "X-1"


def test_check_rules(conn):
    old = _existing(conn)
    items = [
        {"row": 2, "model": "YANGI-TEST-1", "description": "Test", "price_incl_vat": "1456", "unit": "м3/ч", "capacity": "1000"},
        {"row": 3, "model": "YANGI-TEST-2", "price_excl_vat": "1300"},
        {"row": 4, "model": "YANGI-TEST-3", "description": "Narxsiz"},
        {"row": 5, "model": old["model"].lower(), "price_incl_vat": str(old["price_incl_vat"])},
        {"row": 6, "model": "YANGI-TEST-1", "price_incl_vat": "10"},
        {"row": 7, "model": "YANGI-TEST-4", "price_excl_vat": "1480.36", "price_incl_vat": "1658"},
        {"row": 8, "model": "YANGI-TEST-5", "price_excl_vat": "1000", "price_incl_vat": "1500"},
        {"row": 9, "model": "YANGI-TEST-6", "price_incl_vat": "1x", "unit": "litr"},
    ]
    r = {i["row"]: i for i in P.check(conn, items)["items"]}
    assert r[2]["status"] == "new" and Decimal(r[2]["value"]["price_excl_vat"]) * Decimal("1.12") == Decimal("1456")
    assert r[2]["value"]["capacity_unit"] == "m3/h"                       # kirillcha birlik tanildi
    assert r[3]["status"] == "new" and r[3]["value"]["price_incl_vat"] == Decimal("1456")      # ROUNDUP(1300*1.12)
    assert r[4]["status"] == "error"                                      # yangi mahsulot narxsiz — taxmin yo'q
    assert r[5]["status"] in ("same", "changed")                          # katta-kichik harf farqi — o'sha model
    assert r[6]["status"] == "error" and "takrorlangan" in r[6]["errors"][0]
    assert r[7]["status"] == "new" and r[7]["value"]["price_excl_vat"] == Decimal("1658") / Decimal("1.12")  # yaxlitlangan ko'rinish
    assert r[8]["status"] == "new" and any("TEKSHIRISH KERAK" in w for w in r[8]["warnings"])
    assert r[9]["status"] == "error" and len(r[9]["errors"]) == 2


def test_apply_creates_new_version(conn):
    old = _existing(conn)
    admin = conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one()
    before = conn.execute(text("SELECT id FROM price_list WHERE approved_at IS NOT NULL ORDER BY valid_from DESC, id DESC LIMIT 1")).scalar_one()
    n_before = conn.execute(text("SELECT count(*) FROM price_list_item WHERE price_list_id = :i"), {"i": before}).scalar_one()
    new_incl = old["price_incl_vat"] + 112
    res = P.apply(conn, [
        {"row": 2, "model": "YANGI-TEST-APPLY", "description": "Test mahsulot", "brand": "TestBrend-XYZ", "price_incl_vat": "1120"},
        {"row": 3, "model": old["model"], "price_incl_vat": str(new_incl)},
    ], admin, None, "test")
    assert (res["added"], res["changed"], res["copied"]) == (1, 1, n_before - 1)
    assert conn.execute(text("SELECT count(*) FROM price_list_item WHERE price_list_id = :i"),
                        {"i": res["price_list_id"]}).scalar_one() == n_before + 1
    # eski versiya o'zgarmadi, yangi KP lar yangi narxni oladi
    assert conn.execute(text("""SELECT i.price_incl_vat FROM price_list_item i JOIN product p ON p.id = i.product_id
                                WHERE i.price_list_id = :o AND p.model = :m"""), {"o": before, "m": old["model"]}).scalar_one() == old["price_incl_vat"]
    assert svc.current_price_item(conn, "yangi-test-apply").price_excl_vat == Decimal("1000")
    # ÷1,12 cheksiz kasr: o'sha QQS bilan narx qayta berilsa — "o'zgarmagan" (bazadagi numeric bilan kichik xona farqi o'zgarish emas)
    db_excl = conn.execute(text("SELECT 1826 / (1 + 0.12::numeric)")).scalar_one()      # C013 kabi bazada hisoblangan
    assert db_excl != Decimal(1826) / Decimal("1.12")                                    # xonalar soni farq qiladi
    P.apply(conn, [{"row": 2, "model": "YANGI-TEST-1826", "price_excl_vat": str(db_excl), "price_incl_vat": "1826"}],
            admin, None, "test")
    again = P.check(conn, [{"row": 2, "model": "YANGI-TEST-1826", "price_incl_vat": "1 826"}])["items"][0]
    assert again["status"] == "same", again["changes"]
    assert svc.current_price_item(conn, old["model"]).price_excl_vat == new_incl / Decimal("1.12")
    assert conn.execute(text("""SELECT b.name FROM product p JOIN product_series s ON s.id = p.series_id JOIN brand b ON b.id = s.brand_id
                                WHERE p.model = 'YANGI-TEST-APPLY'""")).scalar_one() == "TestBrend-XYZ"


def test_apply_rejects_errors_and_no_changes(conn):
    import pytest
    from fastapi import HTTPException
    old = _existing(conn)
    admin = conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one()
    with pytest.raises(HTTPException) as e:
        P.apply(conn, [{"row": 2, "model": "YANGI-NARXSIZ"}], admin, None, "test")
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        P.apply(conn, [{"row": 2, "model": old["model"], "price_incl_vat": str(old["price_incl_vat"])}], admin, None, "test")


def test_api_permissions_and_flow(client, conn):
    make_user(conn, "t_price_mgr", ["manager"])
    login(client, "t_price_mgr")
    assert client.post("/api/price-list/changes/parse", json={"text": "Model\tЦена с НДС\nX\t1"}).status_code == 403
    assert client.get("/api/price-list/current").status_code == 403
    client.post("/api/auth/logout")

    make_user(conn, "t_price_dir", ["director"])
    login(client, "t_price_dir")
    p = client.post("/api/price-list/changes/parse",
                    json={"text": "Model\tНаименование\tЦена с НДС\nAPI-TEST-HRV\tРекуператор\t1 456"}).json()
    assert p["counts"] == {"new": 1} and p["items"][0]["value"]["price_excl_vat"] == "1300"
    r = client.post("/api/price-list/changes/apply", json={"items": [p["items"][0] | {"row": 2}], "name": "API test versiya"})
    assert r.status_code == 200 and r.json()["added"] == 1
    cur = client.get("/api/price-list/current?q=API-TEST-HRV").json()
    assert [(i["model"], i["price_incl_vat"]) for i in cur["items"]] == [("API-TEST-HRV", "1456")]
    assert client.get("/api/price-list/versions").json()[0]["name"] == "API test versiya"
    # KP katalog qidiruvida ham ko'rinadi
    assert any(i["model"] == "API-TEST-HRV" for i in client.get("/api/price-list/search?q=API-TEST").json())
