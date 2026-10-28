"""KP savdo holati (Jarayonda / Sotildi / Yutqazildi / Loyiha yopildi) va Dashboard (foydalanuvchi qarori 2026-10-16).

Holatni faqat KP menejeri o'zi belgilaydi (deal.update); har o'zgarish tarixda qoladi.
Dashboard (dashboard.view): kp.view_all bo'lsa — hammasi (menejer filtri bilan), aks holda faqat o'z KP lari.
Sanalar: KP soni — KP tuzilgan sana (1-revision), sotuv — sotilgan sana. Summalar USD da, QQS bilan
(UZS dagi KP — shu KP revisionidagi tasdiqlangan kurs bilan USD ga).
"""
import datetime as dt
from decimal import Decimal
from statistics import median
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..db import get_conn, plain, row, rows
from ..deps import CurrentUser, current_user, require

router = APIRouter(prefix="/api", tags=["Savdo holati va dashboard"])

NEEDS_STATUS = ("approved", "sent")          # holat so'raladigan KP lar: tasdiqlangan yoki yuborilgan

# Har KP: menejer, tuzilgan sana, oxirgi revision jami (USD), joriy savdo holati
KP_CTE = """
WITH kp AS (
    SELECT q.id, q.kp_number, q.manager_id, e.full_name AS manager_name, q.project_id, p.name AS project_name,
           (SELECT min(r0.kp_date) FROM quotation_revision r0 WHERE r0.quotation_id = q.id) AS created_on,
           r.id AS revision_id, r.status AS rev_status, r.revision_no, t.total_incl_vat, t.display_currency,
           CASE WHEN t.display_currency = 'USD' THEN 1 ELSE er.rate END AS usd_divisor,
           CASE WHEN t.display_currency = 'USD' THEN t.total_incl_vat ELSE t.total_incl_vat / er.rate END AS total_usd,
           CASE WHEN t.display_currency = 'USD' THEN t.subtotal ELSE t.subtotal / er.rate END AS subtotal_usd,
           CASE WHEN t.display_currency = 'USD' THEN t.discount_amount ELSE t.discount_amount / er.rate END AS discount_usd,
           d.status_code, d.status_name, d.sold_on, d.lost_reason_code, d.lost_reason_name, d.comment, d.created_at AS status_at,
           CASE WHEN d.sold_currency = 'USD' THEN d.sold_amount
                WHEN d.sold_currency = 'UZS' THEN d.sold_amount / er.rate END AS sold_usd
    FROM quotation q
    JOIN project p ON p.id = q.project_id
    JOIN employee e ON e.id = q.manager_id
    JOIN LATERAL (SELECT r.* FROM quotation_revision r WHERE r.quotation_id = q.id ORDER BY r.revision_no DESC LIMIT 1) r ON true
    JOIN v_quotation_totals t ON t.revision_id = r.id
    LEFT JOIN exchange_rate er ON er.id = r.exchange_rate_id
    LEFT JOIN v_quotation_deal d ON d.quotation_id = q.id
    WHERE q.kp_number <= 9999999 AND (CAST(:mgr AS bigint) IS NULL OR q.manager_id = :mgr)
)
"""


@router.get("/deal/meta")
def deal_meta(user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    return {"statuses": rows(conn.execute(text("SELECT code, name FROM deal_status ORDER BY sort_order"))),
            "lost_reasons": rows(conn.execute(text("SELECT code, name FROM lost_reason ORDER BY sort_order")))}


def _quotation(conn: Connection, kp: int, user: CurrentUser):
    q = conn.execute(text(
        """SELECT q.id, q.manager_id, r.status, t.total_incl_vat, t.display_currency FROM quotation q
           JOIN LATERAL (SELECT r.* FROM quotation_revision r WHERE r.quotation_id = q.id ORDER BY r.revision_no DESC LIMIT 1) r ON true
           JOIN v_quotation_totals t ON t.revision_id = r.id WHERE q.kp_number = :k"""), {"k": kp}).mappings().first()
    if q is None or not (user.can("kp.view_all") or (user.can("kp.view_own") and q["manager_id"] == user.employee_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "KP topilmadi")
    return q


@router.get("/quotations/{kp}/deal")
def deal_get(kp: int, user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    q = _quotation(conn, kp, user)
    history = rows(conn.execute(text(
        """SELECT e.id, e.status_code, s.name AS status_name, e.sold_amount, e.sold_currency, e.sold_on, e.lost_reason_code,
                  lr.name AS lost_reason_name, e.comment, e.created_at, emp.full_name AS created_by_name
           FROM quotation_deal_event e JOIN deal_status s ON s.code = e.status_code
           LEFT JOIN lost_reason lr ON lr.code = e.lost_reason_code
           JOIN app_user u ON u.id = e.created_by JOIN employee emp ON emp.id = u.employee_id
           WHERE e.quotation_id = :q ORDER BY e.created_at DESC, e.id DESC"""), {"q": q["id"]}))
    return {"current": history[0] if history else None, "history": history,
            "can_update": user.can("deal.update") and q["manager_id"] == user.employee_id,
            "suggested_amount": plain(q["total_incl_vat"]), "currency": q["display_currency"],
            "needs_status": q["status"] in NEEDS_STATUS and not history}


class DealIn(BaseModel):
    status: Literal["in_progress", "won", "lost", "closed"]
    sold_amount: Decimal | None = Field(None, gt=0, description="Sotildi: QQS bilan, KP valyutasida")
    sold_on: dt.date | None = None
    lost_reason: str | None = None
    comment: str | None = Field(None, max_length=2000)


@router.post("/quotations/{kp}/deal")
def deal_set(kp: int, body: DealIn, user: CurrentUser = Depends(require("deal.update")),
             conn: Connection = Depends(get_conn, scope="function")):
    q = _quotation(conn, kp, user)
    if q["manager_id"] != user.employee_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Holatni faqat KP menejeri o'zi belgilaydi")
    comment = (body.comment or "").strip() or None
    amount = currency = sold_on = reason = None
    if body.status == "won":
        if body.sold_amount is None or body.sold_on is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Sotildi: sotilgan summa va sana majburiy")
        if body.sold_on > dt.date.today():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Sotilgan sana kelajakda bo'lishi mumkin emas")
        amount, currency, sold_on = body.sold_amount, q["display_currency"], body.sold_on
    if body.status == "lost":
        if not body.lost_reason or not comment:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Yutqazildi: sabab va izoh majburiy")
        if not conn.execute(text("SELECT 1 FROM lost_reason WHERE code = :c"), {"c": body.lost_reason}).first():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Sabab topilmadi")
        reason = body.lost_reason
    conn.execute(text(
        """INSERT INTO quotation_deal_event (quotation_id, status_code, sold_amount, sold_currency, sold_on, lost_reason_code, comment, created_by)
           VALUES (:q, :s, :a, :c, :d, :r, :m, :u)"""),
        {"q": q["id"], "s": body.status, "a": amount, "c": currency, "d": sold_on, "r": reason, "m": comment, "u": user.id})
    return deal_get(kp, user, conn)


@router.get("/deal/reminders")
def deal_reminders(user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """Menejerning tasdiqlangan/yuborilgan, lekin savdo holati belgilanmagan KP lari (muloyim eslatma uchun)."""
    if not user.can("deal.update"):
        return {"count": 0, "items": []}
    items = rows(conn.execute(text(KP_CTE + """
        SELECT kp_number, project_name, created_on, total_incl_vat, display_currency FROM kp
        WHERE status_code IS NULL AND rev_status IN ('approved', 'sent') ORDER BY created_on, kp_number"""),
        {"mgr": user.employee_id}))
    return {"count": len(items), "items": items}


GRAN = {"day": "day", "month": "month", "quarter": "quarter", "year": "year"}
STEP = {"day": "1 day", "month": "1 month", "quarter": "3 months", "year": "1 year"}


def _label(d: dt.date, g: str) -> str:
    if g == "day":
        return d.strftime("%d.%m")
    if g == "month":
        return ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"][d.month - 1] + f" {d.year % 100:02d}"
    if g == "quarter":
        return f"{(d.month - 1) // 3 + 1}-chorak {d.year}"
    return str(d.year)


def _trunc(d: dt.date, g: str) -> dt.date:
    if g == "day":
        return d
    if g == "month":
        return d.replace(day=1)
    if g == "quarter":
        return dt.date(d.year, (d.month - 1) // 3 * 3 + 1, 1)
    return dt.date(d.year, 1, 1)


def _buckets(d1: dt.date, d2: dt.date, g: str) -> list[dt.date]:
    out, b = [], _trunc(d1, g)
    while b <= d2 and len(out) < 400:
        out.append(b)
        if g == "day":
            b += dt.timedelta(days=1)
        else:
            m = b.month - 1 + {"month": 1, "quarter": 3, "year": 12}[g]
            b = dt.date(b.year + m // 12, m % 12 + 1, 1)
    return out


# KP hajmi (USD, QQS bilan) va chegirma foizi oraliqlari: [quyi, yuqori)
SIZE_EDGES = [(0, 5_000), (5_000, 10_000), (10_000, 25_000), (25_000, 50_000), (50_000, 100_000), (100_000, 250_000), (250_000, None)]
DISCOUNT_EDGES = [(Decimal(0), Decimal("0.05")), (Decimal("0.05"), Decimal("0.10")), (Decimal("0.10"), Decimal("0.15")),
                  (Decimal("0.15"), Decimal("0.20")), (Decimal("0.20"), None)]


def _ratio(a, b):
    return plain(Decimal(a) / Decimal(b)) if b else None


def _summary(kps: list[dict], first_seen: dict[int, dt.date], d1: dt.date) -> dict:
    """Bir davr KP lari bo'yicha asosiy ko'rsatkichlar. Summasi noma'lum (narxi yo'q qatorli) KP soni alohida —
    summa va o'rtachaga kirmaydi, lekin yashirilmaydi."""
    priced = [k for k in kps if k["total_usd"] is not None]
    total = sum((k["total_usd"] for k in priced), Decimal(0))
    sub = sum((k["subtotal_usd"] for k in priced), Decimal(0))
    disc = [k for k in priced if k["discount_usd"]]
    projects = {k["project_id"] for k in kps}
    return {
        "kp_count": len(kps), "kp_sum_usd": plain(total), "unpriced_count": len(kps) - len(priced),
        "avg_usd": _ratio(total, len(priced)),
        "median_usd": plain(median(k["total_usd"] for k in priced)) if priced else None,
        "revised_count": sum(1 for k in kps if k["revision_no"] > 1),
        "discounted_count": len(disc), "discount_usd": plain(sum((k["discount_usd"] for k in disc), Decimal(0))),
        "discount_rate": _ratio(sum((k["discount_usd"] for k in disc), Decimal(0)), sub),
        "projects": len(projects), "new_projects": sum(1 for pid in projects if first_seen[pid] >= d1),
        "managers": len({k["manager_id"] for k in kps}),
    }


@router.get("/dashboard")
def dashboard(date_from: dt.date | None = None, date_to: dt.date | None = None,
              granularity: Literal["day", "month", "quarter", "year"] = "month", manager_id: int | None = None,
              compare_from: dt.date | None = None, compare_to: dt.date | None = None,
              user: CurrentUser = Depends(require("dashboard.view")), conn: Connection = Depends(get_conn, scope="function")):
    """Taqqoslash davri (compare_from/compare_to) berilmasa — tanlangan davrdan oldingi teng uzunlikdagi davr."""
    if user.can("kp.view_all"):
        mgr = manager_id
    elif user.can("kp.view_own"):
        mgr = user.employee_id                      # menejer — faqat o'z dashboardi
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "KP larni ko'rish ruxsati yo'q")
    today = dt.date.today()
    d1 = date_from or today.replace(day=1)
    d2 = date_to or today
    if d2 < d1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Davr noto'g'ri: boshlanish tugashdan keyin")
    if (compare_from is None) != (compare_to is None) or (compare_from and compare_to < compare_from):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Taqqoslash davri noto'g'ri")
    c2 = compare_to or d1 - dt.timedelta(days=1)
    c1 = compare_from or c2 - (d2 - d1)
    p = {"mgr": mgr, "d1": d1, "d2": d2}
    q = lambda sql: conn.execute(text(KP_CTE + sql), p)

    created = row(q("""SELECT count(*) AS kp_count, coalesce(sum(total_usd), 0) AS kp_sum_usd,
                              count(*) FILTER (WHERE status_code IS NULL) AS unset_count,
                              coalesce(sum(total_usd) FILTER (WHERE status_code IS NULL), 0) AS unset_sum_usd
                       FROM kp WHERE created_on BETWEEN :d1 AND :d2"""))
    by_status = rows(q("""SELECT s.code, s.name, count(kp.id) AS count, coalesce(sum(kp.total_usd), 0) AS sum_usd
                          FROM deal_status s LEFT JOIN kp ON kp.status_code = s.code AND kp.created_on BETWEEN :d1 AND :d2
                          GROUP BY s.code, s.name, s.sort_order ORDER BY s.sort_order"""))
    won = row(q("""SELECT count(*) AS won_count, coalesce(sum(sold_usd), 0) AS won_sum_usd,
                          coalesce(sum(total_usd), 0) AS won_kp_sum_usd
                   FROM kp WHERE status_code = 'won' AND sold_on BETWEEN :d1 AND :d2"""))
    decided = row(q("""SELECT count(*) FILTER (WHERE status_code = 'won') AS won, count(*) FILTER (WHERE status_code = 'lost') AS lost
                       FROM kp WHERE created_on BETWEEN :d1 AND :d2"""))
    lost_reasons = rows(q("""SELECT lr.name, count(kp.id) AS count FROM lost_reason lr
                             LEFT JOIN kp ON kp.lost_reason_code = lr.code AND kp.created_on BETWEEN :d1 AND :d2
                             GROUP BY lr.name, lr.sort_order ORDER BY lr.sort_order"""))
    g = GRAN[granularity]
    series = rows(conn.execute(text(KP_CTE + f"""
        , b AS (SELECT generate_series(date_trunc('{g}', CAST(:d1 AS date)), date_trunc('{g}', CAST(:d2 AS date)), interval '{STEP[g]}')::date AS start)
        SELECT b.start,
               (SELECT count(*) FROM kp WHERE created_on BETWEEN :d1 AND :d2 AND date_trunc('{g}', created_on)::date = b.start) AS kp_count,
               (SELECT coalesce(sum(total_usd), 0) FROM kp WHERE created_on BETWEEN :d1 AND :d2 AND date_trunc('{g}', created_on)::date = b.start) AS kp_sum_usd,
               (SELECT count(*) FROM kp WHERE status_code = 'won' AND sold_on BETWEEN :d1 AND :d2 AND date_trunc('{g}', sold_on)::date = b.start) AS won_count,
               (SELECT coalesce(sum(sold_usd), 0) FROM kp WHERE status_code = 'won' AND sold_on BETWEEN :d1 AND :d2 AND date_trunc('{g}', sold_on)::date = b.start) AS won_sum_usd
        FROM b ORDER BY b.start LIMIT 400"""), p))
    for s in series:
        s["label"] = _label(dt.date.fromisoformat(s["start"]), g)
    managers = []
    if mgr is None:
        managers = rows(q("""SELECT manager_id, manager_name,
                                    count(*) FILTER (WHERE created_on BETWEEN :d1 AND :d2) AS kp_count,
                                    coalesce(sum(total_usd) FILTER (WHERE created_on BETWEEN :d1 AND :d2), 0) AS kp_sum_usd,
                                    count(*) FILTER (WHERE status_code = 'won' AND sold_on BETWEEN :d1 AND :d2) AS won_count,
                                    coalesce(sum(sold_usd) FILTER (WHERE status_code = 'won' AND sold_on BETWEEN :d1 AND :d2), 0) AS won_sum_usd,
                                    count(*) FILTER (WHERE status_code = 'lost' AND created_on BETWEEN :d1 AND :d2) AS lost_count,
                                    count(*) FILTER (WHERE status_code IS NULL AND rev_status IN ('approved', 'sent')) AS unset_count
                             FROM kp GROUP BY manager_id, manager_name
                             HAVING count(*) FILTER (WHERE created_on BETWEEN :d1 AND :d2) > 0
                                 OR count(*) FILTER (WHERE status_code = 'won' AND sold_on BETWEEN :d1 AND :d2) > 0
                             ORDER BY won_sum_usd DESC, kp_sum_usd DESC"""))
    wins = rows(q("""SELECT kp_number, project_name, manager_name, sold_on, sold_usd, total_usd FROM kp
                     WHERE status_code = 'won' AND sold_on BETWEEN :d1 AND :d2 ORDER BY sold_on DESC, sold_usd DESC LIMIT 10"""))
    losses = rows(q("""SELECT kp_number, project_name, manager_name, lost_reason_name, comment, total_usd FROM kp
                       WHERE status_code = 'lost' AND created_on BETWEEN :d1 AND :d2 ORDER BY status_at DESC LIMIT 10"""))
    total_decided = (decided["won"] or 0) + (decided["lost"] or 0)

    # --- Tahlil (2026-10-22): KP lar bir marta o'qiladi, ko'rsatkichlar shu ro'yxatdan (bazaga qayta-qayta so'rov yo'q)
    allkp = [dict(r) for r in q("""SELECT id, kp_number, manager_id, manager_name, project_id, project_name, created_on,
                                          revision_no, total_usd, subtotal_usd, discount_usd FROM kp""").mappings()]
    first_seen: dict[int, dt.date] = {}
    for k in allkp:
        first_seen[k["project_id"]] = min(first_seen.get(k["project_id"], k["created_on"]), k["created_on"])
    cur = [k for k in allkp if d1 <= k["created_on"] <= d2]
    prev = [k for k in allkp if c1 <= k["created_on"] <= c2]
    priced = [k for k in cur if k["total_usd"] is not None]
    cur_total = sum((k["total_usd"] for k in priced), Decimal(0))

    # dinamika: taqqoslash davri ham xuddi shu kesimda, tartib raqami bo'yicha yonma-yon
    prev_b = _buckets(c1, c2, g)
    for i, s in enumerate(series):
        b = prev_b[i] if i < len(prev_b) else None
        inb = [k for k in prev if b and _trunc(k["created_on"], g) == b]
        s.update(prev_label=_label(b, g) if b else None, prev_kp_count=len(inb) if b else None,
                 prev_kp_sum_usd=plain(sum((k["total_usd"] or 0 for k in inb), Decimal(0))) if b else None)

    # menejerlar: o'rtacha KP, loyihalar, chegirma, ulush
    by_mgr: dict[int, list[dict]] = {}
    for k in cur:
        by_mgr.setdefault(k["manager_id"], []).append(k)
    for m in managers:
        ks = by_mgr.get(m["manager_id"], [])
        mp = [k for k in ks if k["total_usd"] is not None]
        msum = sum((k["total_usd"] for k in mp), Decimal(0))
        mdisc = sum((k["discount_usd"] or 0 for k in mp), Decimal(0))
        m.update(avg_usd=_ratio(msum, len(mp)), share=_ratio(msum, cur_total), projects=len({k["project_id"] for k in ks}),
                 discounted_count=sum(1 for k in mp if k["discount_usd"]),
                 discount_rate=_ratio(mdisc, sum((k["subtotal_usd"] for k in mp), Decimal(0))))

    # top loyihalar
    by_prj: dict[int, list[dict]] = {}
    for k in cur:
        by_prj.setdefault(k["project_id"], []).append(k)
    projects = []
    for pid, ks in by_prj.items():
        last = max(ks, key=lambda k: (k["created_on"], k["kp_number"]))
        projects.append({"project_id": pid, "project_name": last["project_name"], "kp_count": len(ks),
                         "kp_sum_usd": plain(sum((k["total_usd"] or 0 for k in ks), Decimal(0))),
                         "managers": sorted({k["manager_name"] for k in ks}), "last_on": last["created_on"].isoformat(),
                         "last_kp": last["kp_number"], "is_new": first_seen[pid] >= d1})
    projects.sort(key=lambda x: Decimal(x["kp_sum_usd"]), reverse=True)

    # KP hajmi taqsimoti
    sizes = []
    for lo, hi in SIZE_EDGES:
        ks = [k for k in priced if k["total_usd"] >= lo and (hi is None or k["total_usd"] < hi)]
        sizes.append({"lo": lo, "hi": hi, "count": len(ks), "sum_usd": plain(sum((k["total_usd"] for k in ks), Decimal(0)))})

    # chegirma: KP ning samarali chegirmasi = chegirma summasi / chegirmagacha summa
    eff = [(k, k["discount_usd"] / k["subtotal_usd"]) for k in priced if k["discount_usd"] and k["subtotal_usd"]]
    disc_buckets = [{"lo": plain(lo), "hi": plain(hi) if hi is not None else None,
                     "count": sum(1 for _, r in eff if r >= lo and (hi is None or r < hi)),
                     "discount_usd": plain(sum((k["discount_usd"] for k, r in eff if r >= lo and (hi is None or r < hi)), Decimal(0)))}
                    for lo, hi in DISCOUNT_EDGES]
    top_disc = [{"kp_number": k["kp_number"], "project_name": k["project_name"], "manager_name": k["manager_name"],
                 "discount_usd": plain(k["discount_usd"]), "rate": plain(r), "total_usd": plain(k["total_usd"])}
                for k, r in sorted(eff, key=lambda x: x[0]["discount_usd"], reverse=True)[:5]]

    # mahsulot kategoriyalari: oxirgi revision qatorlari, ilova chegirmasidan keyin, USD da
    categories = rows(q("""SELECT coalesce(pc.name, 'Kategoriyasiz') AS name, count(DISTINCT kp.id) AS kp_count,
                                  sum(lp.display_line_total * (1 - coalesce(ad.discount_pct, 0)) / kp.usd_divisor) AS sum_usd
                           FROM kp JOIN v_line_price lp ON lp.revision_id = kp.revision_id
                           LEFT JOIN annex_discount ad ON ad.annex_id = lp.annex_id
                           LEFT JOIN product_category pc ON pc.id = lp.category_id
                           WHERE kp.created_on BETWEEN :d1 AND :d2 AND kp.total_usd IS NOT NULL
                           GROUP BY 1 ORDER BY sum_usd DESC NULLS LAST, name"""))

    return {
        "period": {"from": d1.isoformat(), "to": d2.isoformat(), "granularity": g, "manager_id": mgr,
                   "scope": "all" if user.can("kp.view_all") else "own",
                   "compare_from": c1.isoformat(), "compare_to": c2.isoformat()},
        "summary": _summary(cur, first_seen, d1), "previous": _summary(prev, first_seen, c1),
        "categories": categories, "projects": projects[:10], "sizes": sizes,
        "discounts": {"buckets": disc_buckets, "top": top_disc},
        "kpi": {**created, **won,
                "avg_won_usd": plain(Decimal(won["won_sum_usd"]) / won["won_count"]) if won["won_count"] else None,
                "conversion": plain(Decimal(decided["won"]) / total_decided) if total_decided else None,
                "decided_won": decided["won"], "decided_lost": decided["lost"]},
        "by_status": by_status, "lost_reasons": lost_reasons, "series": series,
        "managers": managers, "wins": wins, "losses": losses,
    }
