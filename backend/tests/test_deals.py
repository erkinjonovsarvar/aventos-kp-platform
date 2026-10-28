"""KP savdo holati va Dashboard (foydalanuvchi qarori 2026-10-16)."""
import datetime as dt
from decimal import Decimal

from sqlalchemy import text

from .test_api import client, conn, login, make_user  # noqa: F401  (pytest fixture'lari)


def free_manager(conn):
    """KP lari bor, lekin hali login berilmagan menejer (employee_id UNIQUE)."""
    return conn.execute(text(
        """SELECT q.manager_id FROM quotation q
           WHERE NOT EXISTS (SELECT 1 FROM app_user u WHERE u.employee_id = q.manager_id)
           GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""")).scalar_one()


def own_and_foreign_kp(conn, emp):
    own = conn.execute(text("SELECT kp_number FROM quotation WHERE manager_id = :e ORDER BY kp_number DESC LIMIT 1"), {"e": emp}).scalar_one()
    foreign = conn.execute(text("SELECT kp_number FROM quotation WHERE manager_id <> :e ORDER BY kp_number DESC LIMIT 1"), {"e": emp}).scalar_one()
    return own, foreign


def test_manager_sets_status_on_own_kp_only(client, conn):
    emp = free_manager(conn)
    make_user(conn, "t_seller", ["manager"], employee_id=emp)
    assert login(client, "t_seller").status_code == 200
    own, foreign = own_and_foreign_kp(conn, emp)
    meta = client.get("/api/deal/meta").json()
    assert [s["name"] for s in meta["statuses"]] == ["Jarayonda", "Sotildi", "Yutqazildi", "Loyiha yopildi"]
    d = client.get(f"/api/quotations/{own}/deal").json()
    assert d["current"] is None and d["can_update"] is True
    # majburiy maydonlar
    assert client.post(f"/api/quotations/{own}/deal", json={"status": "won"}).status_code == 422
    assert client.post(f"/api/quotations/{own}/deal", json={"status": "lost", "lost_reason": "price"}).status_code == 422
    assert client.post(f"/api/quotations/{own}/deal", json={"status": "won", "sold_amount": "100",
                                                           "sold_on": (dt.date.today() + dt.timedelta(days=3)).isoformat()}).status_code == 422
    # ketma-ket holatlar — tarixda qoladi
    assert client.post(f"/api/quotations/{own}/deal", json={"status": "in_progress"}).status_code == 200
    r = client.post(f"/api/quotations/{own}/deal", json={"status": "lost", "lost_reason": "price", "comment": "Raqobatchi arzon berdi"})
    assert r.status_code == 200 and r.json()["current"]["lost_reason_name"] == "Narx qimmat"
    r = client.post(f"/api/quotations/{own}/deal", json={"status": "won", "sold_amount": "12345.50", "sold_on": dt.date.today().isoformat()})
    cur = r.json()["current"]
    assert cur["status_code"] == "won" and Decimal(cur["sold_amount"]) == Decimal("12345.50")
    assert [h["status_code"] for h in r.json()["history"]] == ["won", "lost", "in_progress"]
    # begona KP — ko'rinmaydi ham, belgilab ham bo'lmaydi
    assert client.post(f"/api/quotations/{foreign}/deal", json={"status": "in_progress"}).status_code == 404
    # tarix o'zgarmaydi
    import pytest
    with pytest.raises(Exception), conn.begin_nested():
        conn.execute(text("UPDATE quotation_deal_event SET comment = 'x'"))


def test_admin_cannot_set_status_but_sees_it(client, conn):
    make_user(conn, "t_boss", ["admin"])
    login(client, "t_boss")
    kp = conn.execute(text("SELECT max(kp_number) FROM quotation WHERE kp_number <= 9999999")).scalar_one()
    assert client.post(f"/api/quotations/{kp}/deal", json={"status": "in_progress"}).status_code == 403   # deal.update yo'q
    assert client.get(f"/api/quotations/{kp}/deal").status_code == 200


def test_reminders_and_dashboard_scope(client, conn):
    emp = free_manager(conn)
    uid, _ = make_user(conn, "t_seller", ["manager"], employee_id=emp)
    login(client, "t_seller")
    rem = client.get("/api/deal/reminders").json()
    unset_before = rem["count"]
    assert unset_before >= 0
    # dashboard faqat ruxsat berilganda
    assert client.get("/api/dashboard").status_code == 403
    admin = conn.execute(text("SELECT id FROM app_user WHERE login = 'sarvaradmin1'")).scalar()
    conn.execute(text("INSERT INTO user_permission (user_id, permission_code, granted_by) VALUES (:u, 'dashboard.view', :a)"),
                 {"u": uid, "a": admin})
    own, _ = own_and_foreign_kp(conn, emp)
    client.post(f"/api/quotations/{own}/deal", json={"status": "won", "sold_amount": "1000", "sold_on": dt.date.today().isoformat()})
    d = client.get("/api/dashboard", params={"date_from": "2026-01-01", "granularity": "quarter", "manager_id": 1}).json()
    assert d["period"]["scope"] == "own" and d["period"]["manager_id"] == emp       # boshqa menejerni so'rasa ham — faqat o'zi
    assert d["managers"] == []
    assert d["kpi"]["won_count"] >= 1 and Decimal(d["kpi"]["won_sum_usd"]) >= 1000
    assert all(s["label"].endswith("2026") for s in d["series"])
    assert sum(s["kp_count"] for s in d["series"]) == d["kpi"]["kp_count"]
    # admin — hammasi va menejerlar jadvali
    make_user(conn, "t_boss", ["admin"])
    login(client, "t_boss")
    a = client.get("/api/dashboard", params={"date_from": "2026-01-01", "granularity": "month"}).json()
    assert a["period"]["scope"] == "all" and a["managers"] and a["kpi"]["kp_count"] >= d["kpi"]["kp_count"]
    assert {s["code"] for s in a["by_status"]} == {"in_progress", "won", "lost", "closed"}


def test_admin_delete_kp_removes_deal_history(client, conn):
    emp = free_manager(conn)
    make_user(conn, "t_seller", ["manager"], employee_id=emp)
    login(client, "t_seller")
    own, _ = own_and_foreign_kp(conn, emp)
    client.post(f"/api/quotations/{own}/deal", json={"status": "in_progress"})
    make_user(conn, "t_boss", ["admin"])
    login(client, "t_boss")
    assert client.delete(f"/api/quotations/{own}").status_code == 200
    assert conn.execute(text("SELECT count(*) FROM quotation WHERE kp_number = :k"), {"k": own}).scalar_one() == 0
