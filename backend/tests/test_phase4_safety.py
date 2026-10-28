"""Phase 4 (2026-10-20): KP tahrirlash huquqi, bo'sh nomlar, parallel raqamlash qulfi.
Har test ROLLBACK — test bazasida ham hech narsa qolmaydi."""
from sqlalchemy import text

from backend.app import db as app_db
from backend.app import kp_service as svc

from .test_api import client, conn, login, make_user  # noqa: F401  (pytest fixture'lari)


def _two_managers(conn):
    a, b = conn.execute(text("SELECT id FROM employee WHERE is_active ORDER BY id LIMIT 2")).scalars().all()
    return a, b


def _extra(conn, uid, *perms):
    for p in perms:
        conn.execute(text("INSERT INTO user_permission (user_id, permission_code, granted_by) VALUES (:u, :p, :u)"),
                     {"u": uid, "p": p})


def test_manager_with_edit_permission_cannot_touch_other_managers_kp(client, conn):
    """Bazadagi haqiqiy holat: menejerga kp.create_edit + kp.approve qo'shimcha berilgan, ko'rish esa faqat o'ziniki.
    Avval u boshqa menejerning qoralama KP sini tahrirlay va tasdiqlay olardi."""
    mgr_a, mgr_b = _two_managers(conn)
    project = conn.execute(text("SELECT id FROM project ORDER BY id LIMIT 1")).scalar_one()
    make_user(conn, "t_p4_admin", ["admin"])
    login(client, "t_p4_admin")
    kp_a = client.post("/api/quotations", json={"project_id": project, "manager_id": mgr_a}).json()["kp_number"]
    assert client.post(f"/api/quotations/{kp_a}/annexes/1/custom-lines",
                       json={"description": "A qatori", "quantity": "1", "price_excl_vat": "10"}).status_code == 200
    line_a = client.get(f"/api/quotations/{kp_a}").json()["annexes"][0]["lines"][0]["line_id"]
    client.post("/api/auth/logout")

    uid, _ = make_user(conn, "t_p4_mgr_b", ["manager"], employee_id=mgr_b)
    _extra(conn, uid, "kp.create_edit", "kp.approve", "ahu.import", "project.manage")
    assert login(client, "t_p4_mgr_b").status_code == 200
    # boshqa menejerning KP si: ko'rinmaydi va o'zgartirilmaydi (404 — borligi ham oshkor qilinmaydi)
    for method, url, body in [
        ("post", f"/api/quotations/{kp_a}/annexes", {"name": "Begona"}),
        ("post", f"/api/quotations/{kp_a}/annexes/1/custom-lines", {"description": "x", "quantity": "1", "price_excl_vat": "1"}),
        ("patch", f"/api/quotations/{kp_a}/lines/{line_a}", {"quantity": "5"}),
        ("delete", f"/api/quotations/{kp_a}/lines/{line_a}", None),
        ("post", f"/api/quotations/{kp_a}/approve", None),
        ("post", f"/api/quotations/{kp_a}/revisions", None),
    ]:
        r = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
    qty = conn.execute(text("SELECT quantity FROM quotation_line WHERE id = :l"), {"l": line_a}).scalar_one()
    assert qty == 1                                                     # o'zgarmadi
    # boshqa menejer nomidan KP yaratish — taqiqlangan; o'z nomidan — mumkin
    assert client.post("/api/quotations", json={"project_id": project, "manager_id": mgr_a}).status_code == 403
    r = client.post("/api/quotations", json={"project_id": project, "manager_id": mgr_b})
    assert r.status_code == 200, r.text
    kp_b = r.json()["kp_number"]
    assert client.post(f"/api/quotations/{kp_b}/annexes/1/custom-lines",
                       json={"description": "O'z qatori", "quantity": "1", "price_excl_vat": "10"}).status_code == 200


def test_blank_or_padded_names_are_cleaned_or_rejected(client, conn):
    make_user(conn, "t_p4_admin2", ["admin"])
    login(client, "t_p4_admin2")
    assert client.post("/api/projects", json={"name": "    "}).status_code == 422
    r = client.post("/api/projects", json={"name": "  Yangi   loyiha  "})
    assert r.status_code == 200 and r.json()["name"] == "Yangi loyiha"
    manager = conn.execute(text("SELECT id FROM employee WHERE is_active ORDER BY id LIMIT 1")).scalar_one()
    kp = client.post("/api/quotations", json={"project_id": r.json()["id"], "manager_id": manager}).json()["kp_number"]
    assert client.post(f"/api/quotations/{kp}/annexes", json={"name": "   "}).status_code == 422
    assert client.post(f"/api/quotations/{kp}/annexes", json={"name": " VRF  tizimi "}).json()["annex_no"] == 2
    names = conn.execute(text("""SELECT a.name FROM quotation_annex a JOIN quotation_revision r ON r.id = a.revision_id
                                 JOIN quotation q ON q.id = r.quotation_id WHERE q.kp_number = :k ORDER BY a.annex_no"""),
                         {"k": kp}).scalars().all()
    assert names[1] == "VRF tizimi"
    assert client.post(f"/api/quotations/{kp}/annexes/1/custom-lines",
                       json={"description": "   ", "quantity": "1", "price_excl_vat": "1"}).status_code == 422


def test_numbering_lock_blocks_parallel_transaction():
    """Bitta ilova qatorlari raqamlanayotganda ikkinchi tranzaksiya shu qulfni ololmaydi; tugagach — oladi."""
    eng = app_db.engine()
    key = 987654321
    with eng.connect() as c1, eng.connect() as c2:
        c1.begin()
        svc.lock_numbering(c1, "line", key)
        c2.begin()
        try_lock = text("SELECT pg_try_advisory_xact_lock(hashtext('aventos:line'), :k)")
        assert c2.execute(try_lock, {"k": key}).scalar_one() is False
        assert c2.execute(try_lock, {"k": key + 1}).scalar_one() is True       # boshqa ilova — bloklanmaydi
        c2.rollback()
        c1.rollback()                                                       # qulf tranzaksiya bilan bo'shaydi
        c2.begin()
        assert c2.execute(try_lock, {"k": key}).scalar_one() is True
        c2.rollback()
