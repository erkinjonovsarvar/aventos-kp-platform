"""Dashboard tahlili (2026-10-22): KPI, taqqoslash davri, kategoriyalar, loyihalar, KP hajmi va chegirma taqsimoti.
Asosiy tekshiruv — bir xil ma'lumot turli kesimlarda bir xil jamini berishi (ko'rsatkichlar bir-biriga zid emas)."""
import datetime as dt
from decimal import Decimal

from sqlalchemy import text

from .test_api import client, conn, login, make_user  # noqa: F401  (pytest fixture'lari)
from .test_deals import free_manager

D = Decimal


def as_admin(client, conn):
    make_user(conn, "t_dash_boss", ["admin"])
    assert login(client, "t_dash_boss").status_code == 200


def test_summary_is_consistent_across_breakdowns(client, conn):
    as_admin(client, conn)
    d = client.get("/api/dashboard", params={"date_from": "2026-07-01", "date_to": "2026-10-31", "granularity": "month"}).json()
    s = d["summary"]
    assert s["kp_count"] == d["kpi"]["kp_count"] > 0
    assert D(s["kp_sum_usd"]) == D(d["kpi"]["kp_sum_usd"])
    assert D(s["avg_usd"]) == D(s["kp_sum_usd"]) / (s["kp_count"] - s["unpriced_count"])
    # menejerlar — jami KP soni va ulushlar 100%
    assert sum(m["kp_count"] for m in d["managers"]) == s["kp_count"]
    assert abs(sum(D(m["share"]) for m in d["managers"] if m["share"]) - 1) < D("0.000001")
    assert s["managers"] == sum(1 for m in d["managers"] if m["kp_count"])
    # kategoriyalar (qator darajasida, chegirmadan keyin) jami = KP lar jami
    assert abs(sum(D(c["sum_usd"]) for c in d["categories"]) - D(s["kp_sum_usd"])) < D("0.01")
    # KP hajmi taqsimoti — narxi ma'lum har KP bitta oraliqda
    assert sum(b["count"] for b in d["sizes"]) == s["kp_count"] - s["unpriced_count"]
    assert sum(D(b["sum_usd"]) for b in d["sizes"]) == D(s["kp_sum_usd"])
    # chegirma oraliqlari
    assert sum(b["count"] for b in d["discounts"]["buckets"]) == s["discounted_count"]
    assert abs(sum(D(b["discount_usd"]) for b in d["discounts"]["buckets"]) - D(s["discount_usd"])) < D("0.000001")
    assert len(d["discounts"]["top"]) <= 5
    # loyihalar — summa bo'yicha kamayish tartibida, ko'pi bilan 10 ta
    sums = [D(p["kp_sum_usd"]) for p in d["projects"]]
    assert 0 < len(sums) <= 10 and sums == sorted(sums, reverse=True)
    assert s["new_projects"] <= s["projects"]


def test_compare_period(client, conn):
    as_admin(client, conn)
    sep = client.get("/api/dashboard", params={"date_from": "2026-09-01", "date_to": "2026-09-30", "granularity": "month"}).json()
    oct_ = client.get("/api/dashboard", params={"date_from": "2026-10-01", "date_to": "2026-10-30", "granularity": "month",
                                                "compare_from": "2026-09-01", "compare_to": "2026-09-30"}).json()
    assert oct_["period"]["compare_from"] == "2026-09-01" and oct_["period"]["compare_to"] == "2026-09-30"
    assert oct_["previous"]["kp_count"] == sep["summary"]["kp_count"]
    assert D(oct_["previous"]["kp_sum_usd"]) == D(sep["summary"]["kp_sum_usd"])
    # dinamikada taqqoslash davri ham — shu kesimda, yonma-yon
    assert oct_["series"][0]["prev_label"] == "Sen 26" and oct_["series"][0]["prev_kp_count"] == sep["summary"]["kp_count"]
    # berilmasa — oldingi teng uzunlikdagi davr
    auto = client.get("/api/dashboard", params={"date_from": "2026-10-01", "date_to": "2026-10-10"}).json()
    assert (auto["period"]["compare_from"], auto["period"]["compare_to"]) == ("2026-09-21", "2026-09-30")
    bad = {"date_from": "2026-10-01", "date_to": "2026-10-10"}
    assert client.get("/api/dashboard", params={**bad, "compare_from": "2026-09-01"}).status_code == 422
    assert client.get("/api/dashboard", params={**bad, "compare_from": "2026-09-10", "compare_to": "2026-09-01"}).status_code == 422


def test_discount_shows_up(client, conn):
    as_admin(client, conn)
    params = {"date_from": "2026-07-01", "date_to": "2026-10-31"}
    before = client.get("/api/dashboard", params=params).json()["summary"]
    # davrdagi chegirmasiz, narxi ma'lum, yuborilgan KP: yangi revision (qoralama) va 1-ilovaga 10% chegirma
    kp = conn.execute(text(
        """SELECT q.kp_number FROM quotation q
           JOIN LATERAL (SELECT r.* FROM quotation_revision r WHERE r.quotation_id = q.id ORDER BY r.revision_no DESC LIMIT 1) r ON true
           JOIN v_quotation_totals t ON t.revision_id = r.id
           WHERE r.kp_date >= '2026-07-01' AND t.total_incl_vat > 0 AND t.discount_amount = 0 AND r.revision_no = 1
             AND r.status = 'sent' AND q.kp_number <= 9999999
           ORDER BY q.kp_number LIMIT 1""")).scalar_one()
    assert client.post(f"/api/quotations/{kp}/revisions").status_code == 200
    assert client.put(f"/api/quotations/{kp}/annexes/1/discount", json={"discount_pct": "0.10", "reason": "test"}).status_code == 200
    after = client.get("/api/dashboard", params=params).json()
    assert after["summary"]["kp_count"] == before["kp_count"]                     # yangi revision — yangi KP emas
    assert after["summary"]["revised_count"] == before["revised_count"] + 1
    assert after["summary"]["discounted_count"] == before["discounted_count"] + 1
    assert D(after["summary"]["discount_usd"]) > D(before["discount_usd"])
    assert D(after["summary"]["kp_sum_usd"]) < D(before["kp_sum_usd"])
    assert any(D(b["lo"]) == D("0.10") and b["count"] >= 1 for b in after["discounts"]["buckets"])


def test_manager_sees_only_own_analytics(client, conn):
    emp = free_manager(conn)
    uid, _ = make_user(conn, "t_dash_mgr", ["manager"], employee_id=emp)
    admin = conn.execute(text("SELECT id FROM app_user WHERE login = 'sarvaradmin1'")).scalar()
    conn.execute(text("INSERT INTO user_permission (user_id, permission_code, granted_by) VALUES (:u, 'dashboard.view', :a)"),
                 {"u": uid, "a": admin})
    login(client, "t_dash_mgr")
    name = conn.execute(text("SELECT full_name FROM employee WHERE id = :e"), {"e": emp}).scalar_one()
    d = client.get("/api/dashboard", params={"date_from": "2026-01-01", "date_to": dt.date.today().isoformat(), "manager_id": 1}).json()
    own = conn.execute(text("SELECT count(*) FROM quotation WHERE manager_id = :e"), {"e": emp}).scalar_one()
    assert d["period"]["scope"] == "own" and d["summary"]["managers"] <= 1
    assert d["summary"]["kp_count"] <= own
    assert all(p["managers"] == [name] for p in d["projects"])
