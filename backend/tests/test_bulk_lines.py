"""Excel'dan nusxalangan ro'yxat bilan ommaviy qo'shish (2026-10-19). Har test ROLLBACK."""
from decimal import Decimal

from sqlalchemy import text

from backend.app import bulk_lines as B
from .test_api import client, conn, login, make_user  # noqa: F401  (pytest fixture'lari)


def test_parse_and_normalize():
    assert B.norm("avs 12hjdtd") == B.norm("AVS-12HJDTD") == "AVS12HJDTD"
    assert B.norm("АVS-12НJDTD") == "AVS12HJDTD"                     # kirill А, Н
    assert B.to_num("1 234,50") == Decimal("1234.50") and B.to_num("1,234.50") == Decimal("1234.50")
    assert B.to_num("15 шт") == Decimal("15") and B.to_num("") is None and B.to_num("AVS-12") is None
    assert B.to_num("3,6kw") is None                                   # quvvat ustuni son hisoblanmaydi
    rows = B.split_rows("Модель\tКол-во\tЦена\r\nAVS-12HJDTD\t15\t434\n")
    assert rows == [["Модель", "Кол-во", "Цена"], ["AVS-12HJDTD", "15", "434"]]
    assert B.detect_columns(rows) == ({"model": 0, "qty": 1, "price": 2}, True)
    # sarlavhasiz, model ikkinchi ustunda (oldida tartib raqami)
    rows2 = B.split_rows("1\tAVS-12HJDTD\t15\n2\tAVS-15HJDTD\t8")
    assert B.detect_columns(rows2)[0] == {"model": 1, "qty": 2}
    assert B.split_rows("AVS-12HJDTD 15\nAVS-15HJDTD;8") == [["AVS-12HJDTD", "15"], ["AVS-15HJDTD", "8"]]


def test_preview_statuses_and_merge(conn):
    cat = B.catalog(conn)
    m = sorted(cat)[0]
    loose = m.replace("-", " ").lower()
    raw = f"Model\tSoni\n{m}\t2\n{loose}\t3\nYOQ-MODEL-XYZ-777\t1\n{m}\t-1\n{m}\t4"
    p = B.preview(conn, raw)
    st = [(i["model_raw"], i["status"], i["quantity"]) for i in p["items"]]
    assert st[0] == (m, "found", "9")                    # 2 + 3 (yozilishi boshqacha, lekin o'sha model) + 4 birlashdi
    assert len([x for x in st if x[1] != "error"]) == 2
    single = B.preview(conn, f"{loose}	1")["items"][0]
    assert single["status"] == ("corrected" if loose.upper() != m.upper() else "found") and single["model"] == m
    assert ("YOQ-MODEL-XYZ-777", "not_found", "1") in st
    assert any(s == "error" for _, s, _ in st)
    assert B.preview(conn, raw, merge=False)["counts"]["found"] >= 2


def test_bulk_api_adds_lines_in_order(client, conn):
    make_user(conn, "t_bulk", ["admin"])
    login(client, "t_bulk")
    manager = conn.execute(text("SELECT id FROM employee WHERE legacy_manager_id = 1")).scalar_one()
    project = client.post("/api/projects", json={"name": "Test ommaviy"}).json()
    kp = client.post("/api/quotations", json={"project_id": project["id"], "manager_id": manager, "annex_name": "VRF"}).json()["kp_number"]
    p = client.post(f"/api/quotations/{kp}/annexes/1/bulk/preview", json={"text": "AVWT-76HKF5\t2\nMAXSUS-001\t3"}).json()
    assert [i["status"] for i in p["items"]] == ["found", "not_found"]
    r = client.post(f"/api/quotations/{kp}/annexes/1/bulk", json={"items": [
        {"model": "AVWT-76HKF5", "quantity": "2"},
        {"model": "MAXSUS-001", "quantity": "3", "from_catalog": False, "price_excl_vat": "100", "description": "Maxsus blok"}]})
    assert r.status_code == 200 and r.json()["added"] == 2
    lines = client.get(f"/api/quotations/{kp}").json()["annexes"][0]["lines"]
    assert [(ln["model"], ln["line_type"]) for ln in lines] == [("AVWT-76HKF5", "price_list"), ("MAXSUS-001", "custom")]
    # katalogda yo'q modelni "katalogdan" deb yuborish — rad
    bad = client.post(f"/api/quotations/{kp}/annexes/1/bulk", json={"items": [{"model": "MAXSUS-001", "quantity": "1"}]})
    assert bad.status_code == 422


def test_kp_table_paste_and_autocorrect(conn):
    """KP jadvali sarlavhasi bilan (Наименование, Модель, Производительность, Кол-во, Цена с НДС) va sarlavhasiz nusxa."""
    cat = B.catalog(conn)
    if "HFPE-238K4M22/E" not in cat or "AVS-12HJDTD" not in cat:
        import pytest
        pytest.skip("katalogda sinov modellari yo'q")
    t = ("Тип продукта\tНаименование\tМодель\tПроизводительность\tКол-во\tЕд.изм.\tЦена за ед. с НДС\n"
         "VRF\tVRF ВБ (настенный)\tAVS-12HJDTD\t3,6kw\t15\tшт\t434\n"
         "Фанкоил\tкасетный фанкоил\tHFPE-238K4M22\t\t37\tшт\t1 367\n"
         "Монтаж\tмонтаж работы\tMONTAJ-XYZ-1\t\t1\tшт\t1 120")
    p = B.preview(conn, t)
    assert p["columns"]["model"] == 2 and p["columns"]["qty"] == 4 and p["price_vat"] == "incl"
    got = [(i["status"], i["model"], i["quantity"]) for i in p["items"]]
    assert got[0] == ("found", "AVS-12HJDTD", "15")
    assert got[1] == ("corrected", "HFPE-238K4M22/E", "37")            # /E qo'shimchasiz yozilgan
    assert got[2] == ("not_found", None, "1")
    p2 = B.preview(conn, "avs 12hjdtd\t3,6kw\t15\nАVS-12HJDTD (настенный)\t\t2")
    assert p2["columns"] == {"model": 0, "qty": 2}
    assert [(i["status"], i["model"], i["quantity"]) for i in p2["items"]] == [("corrected", "AVS-12HJDTD", "17")]
