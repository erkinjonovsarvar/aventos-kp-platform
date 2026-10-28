"""KP lar, chegirma hisoboti, TEKSHIRISH KERAK yozuvlari (ko'rish)."""
import logging
import subprocess
from datetime import date

from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .. import kp_export, kp_pdf
from ..db import get_conn, row, rows
from ..deps import CurrentUser, current_user, require

log = logging.getLogger("aventos.export")
router = APIRouter(prefix="/api", tags=["KP va hisobotlar"])


def _scope(user: CurrentUser, all_perm: str, own_perm: str) -> int | None:
    """None — hammasi; aks holda faqat shu xodim (menejer) KP lari."""
    if user.can(all_perm):
        return None
    if user.can(own_perm):
        return user.employee_id
    raise HTTPException(status.HTTP_403_FORBIDDEN, f"Bu amal uchun ruxsat yo'q: {all_perm} yoki {own_perm}")


LATEST = """JOIN LATERAL (SELECT r.* FROM quotation_revision r WHERE r.quotation_id = q.id
                           ORDER BY r.revision_no DESC LIMIT 1) r ON true"""


@router.get("/quotations")
def list_quotations(
    user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function"),
    search: str | None = Query(None, description="KP №, loyiha nomi yoki raqami"),
    manager_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
    status_: str | None = Query(None, alias="status", pattern="^(draft|approved|sent)$", description="KP holati (oxirgi revision)"),
    deal: str | None = Query(None, max_length=40, description="Savdo holati kodi yoki 'unset' (belgilanmagan)"),
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
):
    only = _scope(user, "kp.view_all", "kp.view_own")
    where = ["(CAST(:only AS bigint) IS NULL OR q.manager_id = :only)",
             "(CAST(:mgr AS bigint) IS NULL OR q.manager_id = :mgr)",
             "(CAST(:df AS date) IS NULL OR r.kp_date >= :df)", "(CAST(:dt AS date) IS NULL OR r.kp_date <= :dt)",
             "(CAST(:st AS text) IS NULL OR r.status = :st)",
             "(CAST(:deal AS text) IS NULL OR (:deal = 'unset' AND d.status_code IS NULL) OR d.status_code = :deal)",
             """(CAST(:s AS text) IS NULL OR q.kp_number::text LIKE :s || '%' OR p.project_no::text = :s
                 OR p.name ILIKE '%' || :s || '%')"""]
    params = {"only": only, "mgr": manager_id, "df": date_from, "dt": date_to, "s": search, "st": status_, "deal": deal,
              "lim": limit, "off": offset}
    sql = f"""FROM quotation q JOIN project p ON p.id = q.project_id JOIN employee e ON e.id = q.manager_id {LATEST}
              JOIN v_quotation_totals t ON t.revision_id = r.id LEFT JOIN v_quotation_deal d ON d.quotation_id = q.id
              WHERE {' AND '.join(where)}"""
    total = conn.execute(text("SELECT count(*) " + sql), params).scalar_one()
    items = rows(conn.execute(text(
        f"""SELECT q.kp_number, p.project_no, p.name AS project_name, e.id AS manager_id, e.full_name AS manager_name,
                   r.revision_no, r.kp_date, t.valid_until, r.status, t.display_currency, t.annex_count,
                   t.subtotal, t.discount_amount, t.total_incl_vat, t.missing_price_lines, d.status_code AS deal_status, d.status_name AS deal_status_name
            {sql} ORDER BY r.kp_date DESC, q.kp_number DESC LIMIT :lim OFFSET :off"""), params))
    return {"total": total, "items": items}


@router.get("/quotation-managers")
def quotation_managers(user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """KP ro'yxatidagi "Menejer" filtri uchun: ko'rish huquqi doirasidagi KP lari bor xodimlar."""
    only = _scope(user, "kp.view_all", "kp.view_own")
    return rows(conn.execute(text(
        """SELECT e.id, e.full_name, count(*) AS kp_count FROM quotation q JOIN employee e ON e.id = q.manager_id
           WHERE CAST(:only AS bigint) IS NULL OR q.manager_id = :only GROUP BY e.id, e.full_name ORDER BY e.full_name"""),
        {"only": only}))


@router.get("/quotations/{kp_number}")
def get_quotation(kp_number: int, revision_no: int | None = None,
                  user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    only = _scope(user, "kp.view_all", "kp.view_own")
    head = row(conn.execute(text(
        """SELECT q.id AS quotation_id, q.kp_number, p.project_no, p.name AS project_name,
                  e.id AS manager_id, e.full_name AS manager_name, e.phone AS manager_phone
           FROM quotation q JOIN project p ON p.id = q.project_id JOIN employee e ON e.id = q.manager_id
           WHERE q.kp_number = :kp AND (CAST(:only AS bigint) IS NULL OR q.manager_id = :only)"""),
        {"kp": kp_number, "only": only}))
    if head is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "KP topilmadi")
    revisions = rows(conn.execute(text(
        "SELECT revision_no, kp_date, status FROM quotation_revision WHERE quotation_id = :q ORDER BY revision_no"),
        {"q": head["quotation_id"]}))
    rev_no = revision_no or revisions[-1]["revision_no"]
    totals = row(conn.execute(text(
        """SELECT t.* FROM v_quotation_totals t JOIN quotation_revision r ON r.id = t.revision_id
           WHERE r.quotation_id = :q AND r.revision_no = :n"""), {"q": head["quotation_id"], "n": rev_no}))
    if totals is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision topilmadi")
    annexes = rows(conn.execute(text(
        """SELECT t.*, (SELECT count(*) FROM discount_evidence_link k WHERE k.annex_id = t.annex_id) AS evidence_count
           FROM v_annex_totals t WHERE t.revision_id = :r ORDER BY t.annex_no"""), {"r": totals["revision_id"]}))
    lines = rows(conn.execute(text(
        """SELECT lp.line_id, lp.annex_id, lp.line_no, lp.line_type, pc.name AS category, lp.model, lp.description,
                  lp.performance, lp.performance_unit, lp.quantity, lp.unit_code,
                  lp.unit_price_excl_vat, lp.unit_price_incl_vat, lp.display_unit_price, lp.display_line_total,
                  lp.margin_pct, lp.display_unit_net, lp.display_line_net,
                  lp.line_discount_kind, lp.line_discount_value, lp.line_discount_reason,
                  (SELECT count(*) FROM discount_evidence_link k WHERE k.line_id = lp.line_id) AS evidence_count
           FROM v_line_price lp LEFT JOIN product_category pc ON pc.id = lp.category_id
           WHERE lp.revision_id = :r ORDER BY lp.annex_id, lp.line_no"""), {"r": totals["revision_id"]}))
    for a in annexes:
        a["lines"] = [ln for ln in lines if ln["annex_id"] == a["annex_id"]]
    if not user.can("price.view"):          # bazaviy narx va marja — faqat narxga ruxsati borlarga
        for ln in lines:
            ln.pop("unit_price_excl_vat", None)
            ln.pop("margin_pct", None)
    totals["editable"] = totals["status"] == "draft" and revisions[-1]["revision_no"] == totals["revision_no"]
    # Valyuta kursi va almashtirish tarixi (0028: tayyor KP da ham valyuta almashtiriladi)
    rate = row(conn.execute(text(
        """SELECT er.id, er.rate, er.rate_date, er.source FROM quotation_revision r
           JOIN exchange_rate er ON er.id = r.exchange_rate_id WHERE r.id = :r"""), {"r": totals["revision_id"]}))
    currency_changes = rows(conn.execute(text(
        """SELECT c.changed_at, c.status_at_change, c.old_currency, o.rate AS old_rate, c.new_currency, n.rate AS new_rate,
                  e.full_name AS changed_by_name
           FROM revision_currency_change c JOIN app_user u ON u.id = c.changed_by JOIN employee e ON e.id = u.employee_id
           LEFT JOIN exchange_rate o ON o.id = c.old_rate_id LEFT JOIN exchange_rate n ON n.id = c.new_rate_id
           WHERE c.revision_id = :r ORDER BY c.id"""), {"r": totals["revision_id"]}))
    return {**head, "revisions": revisions, "totals": totals, "annexes": annexes,
            "exchange_rate": rate, "currency_changes": currency_changes}


@router.get("/quotations/{kp_number}/export.xlsx")
def export_xlsx(kp_number: int, revision_no: int | None = None,
                cover: str = Query("auto", pattern="^(auto|ahu|vrf|none)$",
                                   description="Muqova: auto (AHU+valve -> AHU, faqat VRF -> VRF), ahu, vrf, none (shablonning eski muqovasi)"),
                vat_separate: bool = Query(False, description="NDS alohida: narxlar QQSsiz, pastida НДС va Сумма с НДС"),
                annex_pages: bool = Query(False, description="Har ilova alohida sahifada (chop etishda)"),
                line_discount_visible: bool = Query(True, description="Mahsulot chegirmasi ko'rinsin: asosiy narx + pastda chegirma; "
                                                    "false — kataklarda darhol chegirmali narx"),
                user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """KP ni Quotation shabloni ko'rinishida Excel'da yuklab olish (KP_EXPORT_RULES.md); 1-sahifada yangi muqova."""
    if not user.can("kp.download"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu amal uchun ruxsat yo'q: kp.download")
    _check_kp_access(conn, user, kp_number)
    image = None
    try:
        h = kp_pdf.head(conn, kp_number, revision_no)
        kind = kp_pdf.resolve_cover(h, cover)
        if kind:
            image = kp_pdf.cover_jpeg(kind, h)
    except kp_pdf.PdfError as e:          # muqova chizilmasa ham KP yuklanadi — shablonning eski muqovasi bilan
        log.warning("KP %s muqova yaratilmadi: %s", kp_number, e)
    except subprocess.TimeoutExpired:
        log.warning("KP %s muqova: Edge javob bermadi", kp_number)
    try:
        name, data = kp_export.build(conn, kp_number, revision_no, cover_image=image, vat_separate=vat_separate,
                                      annex_pages=annex_pages, line_discount_visible=line_discount_visible)
    except kp_export.ExportError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    ascii_name = "".join(ch if ord(ch) < 128 else "_" for ch in name)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


@router.post("/quotations/{kp_number}/send-telegram")
def send_xlsx_to_telegram(kp_number: int, revision_no: int | None = None,
                          cover: str = Query("auto", pattern="^(auto|ahu|vrf|none)$"),
                          vat_separate: bool = Query(False), annex_pages: bool = Query(False),
                          line_discount_visible: bool = Query(True),
                          user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """Bot ichida (Telegram Mini App) fayl yuklab olib bo'lmaydi — Excel bot chatiga yuboriladi (foydalanuvchi talabi 2026-10-21).
    Fayl saytdagi «Excel yuklab olish» ning o'zi (huquq, menejer cheklovi, muqova, NDS alohida — bir xil)."""
    from .. import telegram
    resp = export_xlsx(kp_number, revision_no, cover, vat_separate, annex_pages, line_discount_visible,
                       user=user, conn=conn)
    chat = conn.execute(text("SELECT telegram_chat_id FROM app_user WHERE id = :u"), {"u": user.id}).scalar()
    if not chat:
        raise HTTPException(status.HTTP_409_CONFLICT, "Telegram ulanmagan — «Mening xavfsizligim» → «Telegram'ni ulash»")
    disp = resp.headers.get("content-disposition", "")
    name = unquote(disp.split("filename*=UTF-8''")[-1]) if "filename*=" in disp else f"{kp_number}.xlsx"
    if not telegram.send_document(int(chat), name, bytes(resp.body), f"KP {kp_number}"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Telegram'ga yuborib bo'lmadi — birozdan keyin qayta urinib ko'ring")
    return {"sent": True, "file": name}


@router.get("/quotations/{kp_number}/cover")
def cover_info(kp_number: int, revision_no: int | None = None,
               user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """PDF muqovasi: avtomatik tanlov (ahu | vrf | null — aniq emas, foydalanuvchi tanlaydi)."""
    _check_kp_access(conn, user, kp_number)
    try:
        h = kp_pdf.head(conn, kp_number, revision_no)
    except kp_pdf.PdfError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return {"auto": h["auto_cover"], "categories": h["categories"]}


@router.get("/quotations/{kp_number}/export.pdf")
def export_pdf(kp_number: int, revision_no: int | None = None,
               cover: str = Query("auto", pattern="^(auto|ahu|vrf|none)$"),
               user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function")):
    """KP PDF: muqova (AHU/VRF) + Excel shablonining aynan nusxasi."""
    if not user.can("kp.download"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu amal uchun ruxsat yo'q: kp.download")
    _check_kp_access(conn, user, kp_number)
    try:
        name, data, _ = kp_pdf.build(conn, kp_number, revision_no, cover)
    except (kp_pdf.PdfError, kp_export.ExportError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    ascii_name = "".join(ch if ord(ch) < 128 else "_" for ch in name)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


def _check_kp_access(conn: Connection, user: CurrentUser, kp_number: int) -> None:
    only = _scope(user, "kp.view_all", "kp.view_own")
    if not conn.execute(text("SELECT 1 FROM quotation WHERE kp_number = :k AND (CAST(:o AS bigint) IS NULL OR manager_id = :o)"),
                        {"k": kp_number, "o": only}).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "KP topilmadi")


@router.get("/reports/discounts")
def discount_report(user: CurrentUser = Depends(current_user), conn: Connection = Depends(get_conn, scope="function"),
                    project_no: int | None = None, manager_id: int | None = None,
                    date_from: date | None = None, date_to: date | None = None, only_discounted: bool = False):
    only = _scope(user, "discount.report_all", "discount.report_own")
    params = {"only": only, "pno": project_no, "mgr": manager_id, "df": date_from, "dt": date_to, "od": only_discounted}
    where = """WHERE (CAST(:only AS bigint) IS NULL OR manager_id = :only)
                 AND (CAST(:pno AS int) IS NULL OR project_no = :pno)
                 AND (CAST(:mgr AS bigint) IS NULL OR manager_id = :mgr)
                 AND (CAST(:df AS date) IS NULL OR kp_date >= :df) AND (CAST(:dt AS date) IS NULL OR kp_date <= :dt)
                 AND (NOT :od OR discount_pct IS NOT NULL)"""
    items = rows(conn.execute(text(f"SELECT * FROM v_project_discounts {where} ORDER BY project_no, kp_number, annex_no"), params))
    by_project = rows(conn.execute(text(
        f"""SELECT project_no, project_name, display_currency, count(DISTINCT kp_number) AS kp_count,
                   sum(subtotal) AS subtotal, sum(discount_amount) AS discount_amount,
                   sum(total_after_discount) AS total_after_discount,
                   CASE WHEN sum(subtotal) > 0 THEN sum(discount_amount) / sum(subtotal) END AS discount_share
            FROM v_project_discounts {where}
            GROUP BY project_no, project_name, display_currency ORDER BY project_no, display_currency"""), params))
    return {"by_project": by_project, "items": items}


@router.get("/data-issues")
def list_issues(open_only: bool = True, issue_code: str | None = None,
                user: CurrentUser = Depends(require("data_issue.resolve")), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text(
        """SELECT d.*, e.full_name AS resolved_by_name FROM data_issue d
           LEFT JOIN app_user u ON u.id = d.resolved_by LEFT JOIN employee e ON e.id = u.employee_id
           WHERE (NOT :o OR d.resolved_at IS NULL) AND (CAST(:c AS text) IS NULL OR d.issue_code = :c)
           ORDER BY d.issue_code, d.id"""), {"o": open_only, "c": issue_code}))


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=3, description="Qaror: nima uchun yopilmoqda (ma'lumot o'zgarmaydi)")


@router.post("/data-issues/{issue_id}/resolve")
def resolve_issue(issue_id: int, body: ResolveIn,
                  user: CurrentUser = Depends(require("data_issue.resolve")), conn: Connection = Depends(get_conn, scope="function")):
    """Yozuvni ma'lumotni o'zgartirmasdan yopish ('Shundayligicha qoldir'). Ma'lumot tuzatishlari — alohida skript orqali."""
    r = row(conn.execute(text(
        """UPDATE data_issue SET resolved_by = :u, resolved_at = now(), resolution = :t
           WHERE id = :id AND resolved_at IS NULL RETURNING id, issue_code, resolved_at"""),
        {"u": user.id, "t": body.resolution, "id": issue_id}))
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ochiq yozuv topilmadi")
    return r
