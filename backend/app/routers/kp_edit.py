"""KP yaratish va tahrirlash: AHU fayl yuklash, qatorlar, marja, chegirma, tasdiqlash, yangi revision."""
import datetime as dt
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from .. import bulk_lines
from .. import kp_service as svc
from ..ahu_parser import parse
from ..db import get_conn, plain, row, rows
from ..deps import CurrentUser, require

router = APIRouter(prefix="/api", tags=["KP yaratish va tahrirlash"])
EDIT = require("kp.create_edit")
MAX_UPLOAD = 10 * 1024 * 1024


# ------------------------------------------------------------------ ma'lumotnomalar
@router.get("/projects")
def projects(search: str | None = None, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text(
        """SELECT id, project_no, name FROM project
           WHERE CAST(:s AS text) IS NULL OR name ILIKE '%' || :s || '%' OR project_no::text = :s
           ORDER BY project_no DESC LIMIT 30"""), {"s": (search or "").strip() or None}))


def _clean(v: str) -> str:
    """Boshidagi/oxiridagi bo'sh joy olib tashlanadi, ichidagi ketma-ket bo'sh joylar bittaga (2026-10-20: bazada
    49 ta loyiha nomida chetki bo'sh joy, 17 tasi butunlay bo'sh edi — min_length bo'sh joylardan iborat nomni o'tkazardi)."""
    return " ".join(v.split()) if isinstance(v, str) else v


def _trim(v):
    """Faqat chetki bo'sh joylar (tavsifdagi qator ko'chishlari saqlanadi)."""
    return v.strip() if isinstance(v, str) else v


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)

    _strip = field_validator("name", mode="before")(_clean)


@router.post("/projects")
def create_project(body: ProjectIn, user: CurrentUser = Depends(require("project.manage")),
                   conn: Connection = Depends(get_conn, scope="function")):
    svc.lock_numbering(conn, "project_no")
    return row(conn.execute(text(
        """INSERT INTO project (project_no, name) VALUES ((SELECT coalesce(max(project_no), 1000) + 1 FROM project), :n)
           RETURNING id, project_no, name"""), {"n": body.name.strip()}))


@router.get("/employees")
def employees(user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text("SELECT id, full_name, phone FROM employee WHERE is_active ORDER BY full_name")))


@router.get("/exchange-rates")
def exchange_rates(user: CurrentUser = Depends(require("kp.create_edit", "kp.approve")), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text(
        """SELECT r.id, r.from_currency, r.to_currency, r.rate, r.rate_date, r.source, e.full_name AS approved_by_name
           FROM exchange_rate r JOIN app_user u ON u.id = r.approved_by JOIN employee e ON e.id = u.employee_id
           ORDER BY r.rate_date DESC, r.id DESC LIMIT 20""")))


class RateIn(BaseModel):
    rate: Decimal = Field(gt=0)
    rate_date: dt.date
    source: str = Field(min_length=3, description="Manba (masalan: Markaziy bank, 2026-10-15)")


@router.post("/exchange-rates")
def add_rate(body: RateIn, user: CurrentUser = Depends(require("price.manage")), conn: Connection = Depends(get_conn, scope="function")):
    return row(conn.execute(text(
        """INSERT INTO exchange_rate (from_currency, to_currency, rate, rate_date, source, approved_by)
           VALUES ('USD', 'UZS', :r, :d, :s, :u) RETURNING id, rate, rate_date, source"""),
        {"r": body.rate, "d": body.rate_date, "s": body.source, "u": user.id}))


@router.get("/categories")
def categories(user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text("SELECT id, name FROM product_category ORDER BY name")))


@router.get("/price-list/search")
def price_search(q: str, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text(
        """SELECT DISTINCT ON (p.model) p.model, i.description, i.capacity, i.capacity_unit, i.price_excl_vat, i.price_incl_vat
           FROM price_list_item i JOIN price_list pl ON pl.id = i.price_list_id JOIN product p ON p.id = i.product_id
           WHERE pl.approved_at IS NOT NULL AND (p.model ILIKE '%' || :q || '%' OR i.description ILIKE '%' || :q || '%')
           ORDER BY p.model, pl.valid_from DESC LIMIT 30"""), {"q": q.strip()}))


# Har modelning eng so'nggi tasdiqlangan narxi (katalog: tur = narx ro'yxatidagi tavsif, masalan "VRF наружный блок")
_CATALOG = """
    SELECT DISTINCT ON (p.model) p.model, btrim(i.description) AS type, s.name AS series, i.capacity, i.capacity_unit,
           i.price_excl_vat, i.price_incl_vat
    FROM price_list_item i JOIN price_list pl ON pl.id = i.price_list_id
    JOIN product p ON p.id = i.product_id JOIN product_series s ON s.id = p.series_id
    WHERE pl.approved_at IS NOT NULL
    ORDER BY p.model, pl.valid_from DESC, pl.id DESC"""


@router.get("/price-list/types")
def price_types(user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    """Katalogdagi mahsulot turlari (soni bilan) — model tanlashda filtr uchun."""
    return rows(conn.execute(text(
        f"""SELECT type, count(*) AS models, max(capacity_unit) AS capacity_unit FROM ({_CATALOG}) c
            WHERE coalesce(type, '') <> '' GROUP BY type ORDER BY count(*) DESC, type""")))


@router.get("/price-list/find")
def price_find(type: str | None = None, kw: Decimal | None = None, q: str | None = None,
               user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    """Tur va quvvat bo'yicha qidirish: kW berilsa — eng yaqin quvvatlilar birinchi (masalan "VRF наружный блок", 56)."""
    return rows(conn.execute(text(
        f"""SELECT c.*, abs(c.capacity - CAST(:kw AS numeric)) AS diff FROM ({_CATALOG}) c
            WHERE (CAST(:t AS text) IS NULL OR c.type = :t)
              AND (CAST(:q AS text) IS NULL OR c.model ILIKE '%' || :q || '%' OR c.series ILIKE '%' || :q || '%'
                   OR c.type ILIKE '%' || :q || '%')
              AND (CAST(:kw AS numeric) IS NULL OR c.capacity IS NOT NULL)
            ORDER BY abs(c.capacity - CAST(:kw AS numeric)) NULLS LAST, c.capacity NULLS LAST, c.model
            LIMIT 60"""),
        {"t": (type or "").strip() or None, "q": (q or "").strip() or None, "kw": kw}))


# ------------------------------------------------------------------ AHU fayl
@router.post("/ahu-offers")
async def upload_ahu(file: UploadFile = File(...), fixes: str | None = None, user: CurrentUser = Depends(require("ahu.import")),
                     conn: Connection = Depends(get_conn, scope="function")):
    """fixes — A ustunidagi yorliq xatosi bo'lsa foydalanuvchi tanlovi: {"<qator>": <AHU qatori>} (JSON). Fayl o'zgarmaydi."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Faqat .xlsx fayl")
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Fayl 10 MB dan katta")
    try:
        offer = parse(content, file.filename or "ahu.xlsx")
    except Exception as e:  # noqa: BLE001 — foydalanuvchiga tushunarli xabar
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Faylni o'qib bo'lmadi: {e}") from e
    if fixes:
        try:
            mapping = {int(k): int(v) for k, v in json.loads(fixes).items()}
        except (ValueError, TypeError, AttributeError) as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "fixes noto'g'ri") from e
        ahu_rows = {i.row: i for i in offer.items if i.block == "AHU"}
        for it in offer.items:
            if it.row in mapping and it.block != "AHU":
                if mapping[it.row] not in ahu_rows:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{mapping[it.row]}-qator AHU emas")
                it.parent_row = mapping[it.row]
                offer.warnings = [w for w in offer.warnings if not w.split(" qaysi")[0].endswith(f" {it.row}-qator: '{it.src_label}'")]
                offer.warnings.append(f"{it.block} {it.row}-qator: fayldagi yorliq '{it.src_label}' — foydalanuvchi tanlovi bilan "
                                      f"'{ahu_rows[mapping[it.row]].unit_label}' ({mapping[it.row]}-qator) AHU ga bog'landi")
    offer_id = svc.store_offer(conn, offer, user.id)
    return {**ahu_offer(offer_id, user, conn), "warnings": offer.warnings, "hidden_rows": len(offer.hidden_rows)}


@router.get("/ahu-offers/{offer_id}")
def ahu_offer(offer_id: int, user: CurrentUser = Depends(require("ahu.import")), conn: Connection = Depends(get_conn, scope="function")):
    head = row(conn.execute(text(
        """SELECT o.id, o.project_name_raw, o.offer_date, s.file_name, s.uploaded_at FROM ahu_offer o
           JOIN source_document s ON s.id = o.source_document_id WHERE o.id = :o"""), {"o": offer_id}))
    if head is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AHU fayl topilmadi")
    items = rows(conn.execute(text(
        """SELECT i.id, i.source_row, i.block_code, i.unit_label, i.model, i.description, i.air_flow, i.flow_kg_h,
                  i.quantity, i.unit_price, p.unit_label AS parent_label
           FROM ahu_offer_item i LEFT JOIN ahu_offer_item p ON p.id = i.parent_item_id
           WHERE i.ahu_offer_id = :o ORDER BY i.source_row"""), {"o": offer_id}))
    for i in items:
        if i["block_code"] in ("VRF", "KIT"):
            pi = svc.current_price_item(conn, i["model"])
            i["price_list_price"] = plain(pi.price_excl_vat) if pi else None
    name = (head["project_name_raw"] or "").strip()
    head["project_suggestions"] = rows(conn.execute(text(
        "SELECT id, project_no, name FROM project WHERE :n <> '' AND name ILIKE '%' || :n || '%' ORDER BY project_no DESC LIMIT 5"),
        {"n": name}))
    return {**head, "items": items}


# ------------------------------------------------------------------ KP yaratish
class CreateIn(BaseModel):
    project_id: int
    manager_id: int
    ahu_offer_id: int | None = None
    annex_name: str = Field("AHU", min_length=1, max_length=200)
    kp_number: int | None = Field(None, description="Bo'sh — keyingi raqam (eng kattasi + 1)")
    kp_date: dt.date | None = Field(None, description="Bo'sh — bugun")
    display_currency: str = Field("USD", pattern="^(USD|UZS)$")
    exchange_rate_id: int | None = None

    _strip = field_validator("annex_name", mode="before")(_clean)


@router.post("/quotations")
def create_quotation(body: CreateIn, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    if not svc.can_access_kp(user, body.manager_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Boshqa menejer nomidan KP yaratish uchun ruxsat yo'q (kp.view_all kerak)")
    svc.lock_numbering(conn, "kp_number")               # parallel yaratishda bir xil raqam olinmasin
    kp = body.kp_number or svc.next_kp_number(conn)
    if conn.execute(text("SELECT 1 FROM quotation WHERE kp_number = :k"), {"k": kp}).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"KP № {kp} allaqachon bor")
    if body.display_currency == "UZS" and not body.exchange_rate_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "UZS uchun tasdiqlangan kurs tanlanishi shart")
    kp_date = body.kp_date or dt.date.today()
    vat = conn.execute(text("SELECT id FROM vat_rate WHERE valid_from <= :d ORDER BY valid_from DESC LIMIT 1"),
                       {"d": kp_date}).scalar()
    if vat is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bu sana uchun QQS stavkasi kiritilmagan")
    qid = conn.execute(text(
        """INSERT INTO quotation (kp_number, project_id, manager_id, created_by) VALUES (:k, :p, :m, :u) RETURNING id"""),
        {"k": kp, "p": body.project_id, "m": body.manager_id, "u": user.id}).scalar_one()
    rid = conn.execute(text(
        """INSERT INTO quotation_revision (quotation_id, revision_no, kp_date, display_currency, exchange_rate_id, vat_rate_id)
           VALUES (:q, 1, :d, :c, :r, :v) RETURNING id"""),
        {"q": qid, "d": kp_date, "c": body.display_currency, "r": body.exchange_rate_id, "v": vat}).scalar_one()
    aid = conn.execute(text("INSERT INTO quotation_annex (revision_id, annex_no, name) VALUES (:r, 1, :n) RETURNING id"),
                       {"r": rid, "n": body.annex_name.strip() or "AHU"}).scalar_one()
    warnings = svc.build_lines_from_offer(conn, aid, body.ahu_offer_id) if body.ahu_offer_id else []
    if body.ahu_offer_id:
        conn.execute(text("UPDATE ahu_offer SET project_id = :p WHERE id = :o AND project_id IS NULL"),
                     {"p": body.project_id, "o": body.ahu_offer_id})
    return {"kp_number": kp, "revision_no": 1, "warnings": warnings}


class AnnexIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    _strip = field_validator("name", mode="before")(_clean)


@router.post("/quotations/{kp}/annexes")
def add_annex(kp: int, body: AnnexIn, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    n = svc.next_annex_no(conn, rev["id"])
    if n > 12:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ko'pi bilan 12 ta ilova")
    conn.execute(text("INSERT INTO quotation_annex (revision_id, annex_no, name) VALUES (:r, :n, :nm)"),
                 {"r": rev["id"], "n": n, "nm": body.name.strip()})
    return {"annex_no": n}


@router.patch("/quotations/{kp}/annexes/{annex_no}")
def rename_annex(kp: int, annex_no: int, body: AnnexIn, user: CurrentUser = Depends(EDIT),
                 conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    conn.execute(text("UPDATE quotation_annex SET name = :nm WHERE id = :a"), {"nm": body.name.strip(), "a": _annex_id(conn, rev, annex_no)})
    return {"ok": True}


@router.delete("/quotations/{kp}/annexes/{annex_no}")
def delete_annex(kp: int, annex_no: int, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    """Ilovani qatorlari bilan o'chirish; keyingi ilovalar raqami bittaga suriladi (KP da kamida 1 ta ilova qoladi)."""
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    svc.lock_numbering(conn, "annex", rev["id"])          # keyingi ilovalar raqami suriladi
    aid = _annex_id(conn, rev, annex_no)
    if conn.execute(text("SELECT count(*) FROM quotation_annex WHERE revision_id = :r"), {"r": rev["id"]}).scalar_one() <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "KP da kamida bitta ilova qolishi kerak")
    conn.execute(text("DELETE FROM quotation_line WHERE annex_id = :a"), {"a": aid})
    conn.execute(text("DELETE FROM quotation_annex WHERE id = :a"), {"a": aid})
    later = conn.execute(text("SELECT id FROM quotation_annex WHERE revision_id = :r AND annex_no > :n ORDER BY annex_no"),
                         {"r": rev["id"], "n": annex_no}).scalars().all()
    for x in later:                                       # bittadan — UNIQUE (revision_id, annex_no) buzilmasin
        conn.execute(text("UPDATE quotation_annex SET annex_no = annex_no - 1 WHERE id = :a"), {"a": x})
    return {"ok": True}


class AhuAddIn(BaseModel):
    ahu_offer_id: int
    annex_no: int | None = Field(None, description="Bo'sh — yangi ilova yaratiladi; raqam — shu ilova oxiriga qo'shiladi")
    name: str = Field("AHU", min_length=1, max_length=200, description="Yangi ilova nomi")

    _strip = field_validator("name", mode="before")(_clean)


@router.post("/quotations/{kp}/ahu")
def add_ahu(kp: int, body: AhuAddIn, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    """Mavjud KP ga AHU faylini qo'shish (2026-10-20): avval VRF/katalog bilan ochilgan KP ga ham, 2-, 3-ilova sifatida ham."""
    if not user.can("ahu.import"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "AHU fayl yuklashga ruxsat yo'q")
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    if not conn.execute(text("SELECT 1 FROM ahu_offer WHERE id = :o"), {"o": body.ahu_offer_id}).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AHU fayli topilmadi — qayta yuklang")
    if body.annex_no is None:
        n = svc.next_annex_no(conn, rev["id"])
        if n > 12:
            raise HTTPException(status.HTTP_409_CONFLICT, "Ko'pi bilan 12 ta ilova")
        aid = conn.execute(text("INSERT INTO quotation_annex (revision_id, annex_no, name) VALUES (:r, :n, :nm) RETURNING id"),
                           {"r": rev["id"], "n": n, "nm": body.name.strip() or "AHU"}).scalar_one()
    else:
        n = body.annex_no
        aid = _annex_id(conn, rev, n)
    start = svc.next_line_no(conn, aid)
    warnings = svc.build_lines_from_offer(conn, aid, body.ahu_offer_id, start)
    added = conn.execute(text("SELECT count(*) FROM quotation_line WHERE annex_id = :a AND line_no > :s"), {"a": aid, "s": start}).scalar_one()
    conn.execute(text("""UPDATE ahu_offer SET project_id = (SELECT project_id FROM quotation WHERE kp_number = :k)
                         WHERE id = :o AND project_id IS NULL"""), {"k": kp, "o": body.ahu_offer_id})
    return {"annex_no": n, "added": added, "warnings": warnings}


class PriceLineIn(BaseModel):
    model: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    category: str | None = Field(None, description="KP dagi kategoriya (Product Category nomi), masalan 'VRF'")

    _strip = field_validator("model", mode="before")(_trim)


@router.post("/quotations/{kp}/annexes/{annex_no}/lines")
def add_line(kp: int, annex_no: int, body: PriceLineIn, user: CurrentUser = Depends(EDIT),
             conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    aid = conn.execute(text("SELECT id FROM quotation_annex WHERE revision_id = :r AND annex_no = :n"),
                       {"r": rev["id"], "n": annex_no}).scalar()
    if aid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ilova topilmadi")
    n = svc.next_line_no(conn, aid) + 1
    cat = None
    if body.category:
        cat = conn.execute(text("SELECT id FROM product_category WHERE name = :n"), {"n": body.category}).scalar()
        if cat is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Kategoriya topilmadi: {body.category}")
    model = body.model.strip()
    target = svc.merge_target(conn, aid, model, "price_list" if svc.current_price_item(conn, model) else "custom")
    if target is not None:                       # takror model — birinchi qatoriga yig'iladi (qaror 2026-10-21)
        merged = svc.merge_into(conn, target, body.quantity)
        return {"line_no": merged["line_no"], "warnings": [], "merged": merged}
    warnings: list[str] = []
    svc.add_price_list_line(conn, aid, n, model, body.quantity, warnings, cat)
    return {"line_no": n, "warnings": warnings, "merged": None}


def _annex_id(conn, rev, annex_no: int) -> int:
    aid = conn.execute(text("SELECT id FROM quotation_annex WHERE revision_id = :r AND annex_no = :n"),
                       {"r": rev["id"], "n": annex_no}).scalar()
    if aid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ilova topilmadi")
    return aid


@router.get("/quotations/{kp}/annexes/{annex_no}/accessories")
def accessories(kp: int, annex_no: int, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    """Kasseta/kanalniy bloklar uchun panel va pult yetarlimi (qo'lda qo'shilganda ogohlantirish uchun)."""
    need = svc.accessory_needs(conn, _annex_id(conn, svc.revision_for(conn, kp, user=user), annex_no))
    return {"panels": [{k: plain(v) for k, v in p.items()} for p in need["panels"]],
            "pult": {k: plain(v) for k, v in need["pult"].items()}}


class AccessoriesIn(BaseModel):
    panels: bool = False
    pult: bool = False


@router.post("/quotations/{kp}/annexes/{annex_no}/accessories")
def add_accessories(kp: int, annex_no: int, body: AccessoriesIn, user: CurrentUser = Depends(EDIT),
                    conn: Connection = Depends(get_conn, scope="function")):
    """'Ha' — yetishmagan panellar o'z kasseta guruhidan keyin, pult oxirida, soniga qarab qo'shiladi."""
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    return {"added": svc.add_accessories(conn, _annex_id(conn, rev, annex_no), body.panels, body.pult)}


class CustomLineIn(BaseModel):
    description: str = Field(min_length=1, description="Наименование")
    model: str | None = None
    category: str | None = None
    quantity: Decimal = Field(gt=0)
    unit: str = "шт"
    price_excl_vat: Decimal = Field(ge=0, description="QQSsiz narx (marjagacha), KP valyutasida emas — USD")

    _strip = field_validator("description", "model", mode="before")(_trim)


@router.post("/quotations/{kp}/annexes/{annex_no}/custom-lines")
def add_custom(kp: int, annex_no: int, body: CustomLineIn, user: CurrentUser = Depends(EDIT),
               conn: Connection = Depends(get_conn, scope="function")):
    """Narx ro'yxatida yo'q mahsulot (montaj, maxsus model ...) — narxni foydalanuvchi kiritadi."""
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    aid = conn.execute(text("SELECT id FROM quotation_annex WHERE revision_id = :r AND annex_no = :n"),
                       {"r": rev["id"], "n": annex_no}).scalar()
    if aid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ilova topilmadi")
    if not conn.execute(text("SELECT 1 FROM unit WHERE code = :u"), {"u": body.unit}).first():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Birlik topilmadi: {body.unit}")
    cat = None
    if body.category:
        cat = conn.execute(text("SELECT id FROM product_category WHERE name = :n"), {"n": body.category}).scalar()
        if cat is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Kategoriya topilmadi: {body.category}")
    n = svc.next_line_no(conn, aid) + 1
    model = (body.model or "").strip() or None
    target = svc.merge_target(conn, aid, model, "custom", body.price_excl_vat)
    if target is not None:                       # takror model, narxi bir xil — birinchi qatoriga yig'iladi
        merged = svc.merge_into(conn, target, body.quantity)
        return {"line_no": merged["line_no"], "merged": merged}
    svc.add_custom_line(conn, aid, n, description=body.description.strip(), model=model,
                        category_id=cat, quantity=body.quantity, unit=body.unit, price_excl_vat=body.price_excl_vat,
                        currency="USD")
    return {"line_no": n, "merged": None}


# ------------------------------------------------------------------ Excel'dan ro'yxat bilan ommaviy qo'shish (2026-10-19)
class BulkPreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=bulk_lines.MAX_TEXT, description="Excel'dan nusxalangan qatorlar (Model, Soni, [Narx])")
    merge: bool = True


@router.post("/quotations/{kp}/annexes/{annex_no}/bulk/preview")
def bulk_preview(kp: int, annex_no: int, body: BulkPreviewIn, user: CurrentUser = Depends(EDIT),
                 conn: Connection = Depends(get_conn, scope="function")):
    """Ro'yxatni tahlil qilish (bazaga hech narsa yozilmaydi): har qator — topildi / o'xshash / topilmadi / xato."""
    svc.require_draft(svc.revision_for(conn, kp, user=user))
    try:
        return bulk_lines.preview(conn, body.text, body.merge)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e


class BulkItemIn(BaseModel):
    model: str = Field(min_length=1, max_length=120)
    quantity: Decimal = Field(gt=0)
    from_catalog: bool = True
    price_excl_vat: Decimal | None = Field(None, ge=0, description="Katalogda yo'q: QQSsiz narx (USD) — foydalanuvchi yozadi")
    description: str | None = Field(None, max_length=500)

    _strip = field_validator("model", "description", mode="before")(_trim)


class BulkIn(BaseModel):
    items: list[BulkItemIn] = Field(min_length=1, max_length=bulk_lines.MAX_ROWS)


@router.post("/quotations/{kp}/annexes/{annex_no}/bulk")
def bulk_add(kp: int, annex_no: int, body: BulkIn, user: CurrentUser = Depends(EDIT),
             conn: Connection = Depends(get_conn, scope="function")):
    """Tasdiqlangan ro'yxatni bitta tranzaksiyada qo'shish (tartib saqlanadi). Katalogdagi — narx ro'yxatidan,
    katalogda yo'q — foydalanuvchi bergan narx bilan (narx berilmasa — narxsiz, TEKSHIRISH KERAK)."""
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    aid = _annex_id(conn, rev, annex_no)
    n = svc.next_line_no(conn, aid)
    cat = {m.upper().strip(): m for m in bulk_lines.catalog(conn)}    # katta-kichik harf farq qilmaydi (2026-10-21)
    warnings: list[str] = []
    ids: list[int] = []
    merged: dict[int, dict] = {}                 # mavjud qatorga yig'ilganlar: line_id -> {line_id, line_no, old_quantity}
    for it in body.items:
        model = it.model.strip()
        if it.from_catalog and model.upper() in cat:
            model = cat[model.upper()]           # katalogdagi yozilishi
        if it.from_catalog and model.upper() not in cat:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{model}' katalogda yo'q — qo'lda narx bilan qo'shing")
        if it.from_catalog or it.price_excl_vat is None:
            kind, price = ("price_list" if svc.current_price_item(conn, model) else "custom"), None
        else:
            kind, price = "custom", it.price_excl_vat
        target = svc.merge_target(conn, aid, model, kind, price)
        if target is not None:                   # takror model — birinchi qatoriga yig'iladi (qaror 2026-10-21)
            m = svc.merge_into(conn, target, it.quantity)
            if target.id not in ids:             # shu ro'yxatda yaratilgan qator bo'lsa — bekor qilishda baribir o'chadi
                merged.setdefault(target.id, m)  # bekor qilish uchun ENG BIRINCHI oldingi son saqlanadi
            continue
        n += 1
        if kind == "custom" and price is not None:
            ids.append(svc.add_custom_line(conn, aid, n, description=(it.description or model).strip(), model=model,
                                           category_id=None, quantity=it.quantity, unit="шт",
                                           price_excl_vat=price, currency="USD"))
        else:
            ids.append(svc.add_price_list_line(conn, aid, n, model, it.quantity, warnings))   # narxsiz — TEKSHIRISH KERAK
    return {"added": len(ids), "line_ids": ids, "merged": list(merged.values()), "warnings": warnings}


@router.get("/units")
def units(user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text("SELECT code, kind FROM unit WHERE kind = 'quantity' ORDER BY code")))


def _line_of(conn, rev_id: int, line_id: int):
    ln = conn.execute(text(
        """SELECT l.* FROM quotation_line l JOIN quotation_annex a ON a.id = l.annex_id
           WHERE l.id = :l AND a.revision_id = :r"""), {"l": line_id, "r": rev_id}).mappings().first()
    if ln is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Qator topilmadi")
    return ln


class LineUpdateIn(BaseModel):
    margin_pct: Decimal | None = Field(None, ge=0, lt=1, description="0.10 = 10%")
    quantity: Decimal | None = Field(None, gt=0)
    # faqat o'z narxi bilan (custom) qatorlar uchun: narx ro'yxatida yo'q mahsulot narxini foydalanuvchi qo'lda yozadi
    unit_price_excl_vat: Decimal | None = Field(None, ge=0, description="Narx QQSsiz, USD (marjagacha)")
    description: str | None = Field(None, min_length=1)

    _strip = field_validator("description", mode="before")(_trim)


@router.patch("/quotations/{kp}/lines/{line_id}")
def update_line(kp: int, line_id: int, body: LineUpdateIn, user: CurrentUser = Depends(EDIT),
                conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    ln = _line_of(conn, rev["id"], line_id)
    if body.margin_pct is not None:
        if ln["line_type"] == "price_list":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Narx ro'yxati modellariga marja qo'shilmaydi (CLAUDE.md)")
        conn.execute(text("UPDATE quotation_line SET margin_pct = :m WHERE id = :l"), {"m": body.margin_pct, "l": line_id})
    if body.quantity is not None:
        conn.execute(text("UPDATE quotation_line SET quantity = :q WHERE id = :l"), {"q": body.quantity, "l": line_id})
    if body.unit_price_excl_vat is not None or body.description is not None:
        if ln["line_type"] != "custom":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "Narx va tavsif faqat o'z narxi bilan qo'shilgan qatorda qo'lda o'zgartiriladi")
        if body.unit_price_excl_vat is not None:
            conn.execute(text("UPDATE quotation_line_custom SET unit_price_excl_vat = :p WHERE line_id = :l"),
                         {"p": body.unit_price_excl_vat, "l": line_id})
        if body.description is not None and body.description.strip():
            conn.execute(text("UPDATE quotation_line_custom SET description = :d WHERE line_id = :l"),
                         {"d": body.description.strip(), "l": line_id})
    return row(conn.execute(text(
        "SELECT line_id, margin_pct, quantity, unit_price_excl_vat, unit_price_incl_vat, display_line_total FROM v_line_price WHERE line_id = :l"),
        {"l": line_id}))


@router.delete("/quotations/{kp}/lines/{line_id}")
def delete_line(kp: int, line_id: int, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    _line_of(conn, rev["id"], line_id)
    conn.execute(text("DELETE FROM quotation_line WHERE id = :l"), {"l": line_id})
    return {"ok": True}


class DiscountIn(BaseModel):
    discount_pct: Decimal = Field(gt=0, lt=1, description="0.15 = 15%")
    reason: str | None = None


@router.put("/quotations/{kp}/annexes/{annex_no}/discount")
def set_discount(kp: int, annex_no: int, body: DiscountIn, user: CurrentUser = Depends(require("discount.manage")),
                 conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    aid = conn.execute(text("SELECT id FROM quotation_annex WHERE revision_id = :r AND annex_no = :n"),
                       {"r": rev["id"], "n": annex_no}).scalar()
    if aid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ilova topilmadi")
    conn.execute(text("DELETE FROM annex_discount WHERE annex_id = :a"), {"a": aid})
    conn.execute(text("INSERT INTO annex_discount (annex_id, discount_pct, reason, created_by) VALUES (:a, :p, :r, :u)"),
                 {"a": aid, "p": body.discount_pct, "r": body.reason, "u": user.id})
    return row(conn.execute(text("SELECT * FROM v_annex_totals WHERE annex_id = :a"), {"a": aid}))


class LineDiscountIn(BaseModel):
    kind: str = Field(pattern="^(pct|amount)$", description="pct — foiz (0.05 = 5%); amount — 1 dona uchun summa, KP valyutasida")
    value: Decimal = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000, description="Chegirma sababi (majburiy)")

    _strip = field_validator("reason", mode="before")(_trim)


@router.put("/quotations/{kp}/lines/{line_id}/discount")
def set_line_discount(kp: int, line_id: int, body: LineDiscountIn, user: CurrentUser = Depends(require("discount.manage")),
                      conn: Connection = Depends(get_conn, scope="function")):
    """Mahsulot (qator) chegirmasi (foydalanuvchi qarori 2026-10-22, Alembic 0025): QQS bilan 1 dona narxidan foiz yoki summa,
    chegirmali narx ROUNDUP(…, 0); keyin ilova chegirmasi. Faqat admin (bazada ham tekshiriladi), faqat qoralamada."""
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    _line_of(conn, rev["id"], line_id)
    price = conn.execute(text("SELECT display_unit_price FROM v_line_price WHERE line_id = :l"), {"l": line_id}).scalar()
    if price is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Qatorning narxi noma'lum — avval narxni kiriting")
    if body.kind == "pct" and body.value >= 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Foiz 100% dan kichik bo'lishi kerak (0.05 = 5%)")
    if body.kind == "amount" and body.value >= price:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Chegirma summasi 1 dona narxidan ({price}) kichik bo'lishi kerak")
    conn.execute(text("DELETE FROM line_discount WHERE line_id = :l"), {"l": line_id})
    conn.execute(text("INSERT INTO line_discount (line_id, kind, value, reason, created_by) VALUES (:l, :k, :v, :r, :u)"),
                 {"l": line_id, "k": body.kind, "v": body.value, "r": body.reason, "u": user.id})
    return row(conn.execute(text(
        """SELECT line_id, display_unit_price, display_unit_net, display_line_total, display_line_net,
                  line_discount_kind, line_discount_value, line_discount_reason FROM v_line_price WHERE line_id = :l"""),
        {"l": line_id}))


@router.delete("/quotations/{kp}/lines/{line_id}/discount")
def remove_line_discount(kp: int, line_id: int, user: CurrentUser = Depends(require("discount.manage")),
                         conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    _line_of(conn, rev["id"], line_id)
    conn.execute(text("DELETE FROM line_discount WHERE line_id = :l"), {"l": line_id})
    return {"ok": True}


@router.delete("/quotations/{kp}/annexes/{annex_no}/discount")
def remove_discount(kp: int, annex_no: int, user: CurrentUser = Depends(require("discount.manage")),
                    conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    conn.execute(text(
        """DELETE FROM annex_discount WHERE annex_id =
           (SELECT id FROM quotation_annex WHERE revision_id = :r AND annex_no = :n)"""), {"r": rev["id"], "n": annex_no})
    return {"ok": True}


@router.post("/quotations/{kp}/approve")
def approve(kp: int, user: CurrentUser = Depends(require("kp.approve")), conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    svc.require_draft(rev)
    problems = svc.approval_problems(conn, rev["id"])
    if problems:
        raise HTTPException(status.HTTP_409_CONFLICT, "KP tasdiqlanmadi: " + "; ".join(problems))
    conn.execute(text(
        "UPDATE quotation_revision SET status = 'approved', approved_by = :u, approved_at = now() WHERE id = :r"),
        {"u": user.id, "r": rev["id"]})
    return {"kp_number": kp, "revision_no": rev["revision_no"], "status": "approved"}


@router.post("/quotations/{kp}/send")
def mark_sent(kp: int, user: CurrentUser = Depends(require("kp.approve")), conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    if rev["status"] != "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Faqat tasdiqlangan KP yuborilgan deb belgilanadi")
    conn.execute(text("UPDATE quotation_revision SET status = 'sent' WHERE id = :r"), {"r": rev["id"]})
    return {"kp_number": kp, "revision_no": rev["revision_no"], "status": "sent"}


class CurrencyIn(BaseModel):
    display_currency: str = Field(pattern="^(USD|UZS)$")
    exchange_rate_id: int | None = None
    revision_no: int | None = None


@router.put("/quotations/{kp}/currency")
def change_currency(kp: int, body: CurrencyIn, user: CurrentUser = Depends(require("kp.approve", "kp.create_edit")),
                    conn: Connection = Depends(get_conn, scope="function")):
    """KP valyutasini (USD <-> UZS) shu revisionning o'zida almashtirish — tayyor (tasdiqlangan/yuborilgan) KP da ham
    (foydalanuvchi qarori 2026-10-28). Revision raqami va holati o'zgarmaydi. Tayyor KP — faqat kp.approve, qoralama —
    kp.create_edit ham. Kurs — faqat tasdiqlangan exchange_rate dan tanlanadi. Tekshiruv va tarix bazaning o'zida
    (change_revision_currency(), migratsiya 0028)."""
    rev = svc.revision_for(conn, kp, body.revision_no, user=user)
    if rev["status"] != "draft" and not user.can("kp.approve"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tayyor KP ning valyutasini faqat KP ni tasdiqlay oladigan xodim almashtiradi")
    if body.display_currency == "UZS" and not body.exchange_rate_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "UZS uchun tasdiqlangan kursni tanlang")
    try:
        conn.execute(text("SELECT change_revision_currency(:r, :c, :e)"),
                     {"r": rev["id"], "c": body.display_currency,
                      "e": body.exchange_rate_id if body.display_currency == "UZS" else None})
    except DBAPIError as e:                 # bazadagi tekshiruv xabari foydalanuvchiga o'zicha
        diag = getattr(e.orig, "diag", None)
        code = {"42501": status.HTTP_403_FORBIDDEN, "22023": status.HTTP_422_UNPROCESSABLE_ENTITY,
                "P0001": status.HTTP_409_CONFLICT, "P0002": status.HTTP_404_NOT_FOUND}.get(getattr(e.orig, "sqlstate", None))
        if code is None or diag is None:
            raise
        raise HTTPException(code, diag.message_primary) from None
    return {"kp_number": kp, "revision_no": rev["revision_no"], "display_currency": body.display_currency}


@router.post("/quotations/{kp}/revisions")
def new_revision(kp: int, user: CurrentUser = Depends(EDIT), conn: Connection = Depends(get_conn, scope="function")):
    rev = svc.revision_for(conn, kp, user=user)
    if rev["status"] == "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Oxirgi revision hali qoralama — o'shani tahrirlang")
    new_id = svc.copy_revision(conn, rev, user.id)
    no = conn.execute(text("SELECT revision_no FROM quotation_revision WHERE id = :r"), {"r": new_id}).scalar_one()
    return {"kp_number": kp, "revision_no": no, "status": "draft"}


@router.delete("/quotations/{kp}")
def delete_quotation(kp: int, user: CurrentUser = Depends(require("kp.delete")),
                     conn: Connection = Depends(get_conn, scope="function")):
    """KP ni BUTUNLAY o'chirish — har qanday holatda (qoralama, tasdiqlangan, yuborilgan), barcha revisionlari bilan.
    Faqat admin (kp.delete). Ruxsat bazaning o'zida ham tekshiriladi (delete_quotation(), migratsiya 0009).
    O'chirilgan ma'lumot audit_log da qoladi; raqam qayta ishlatilmaydi."""
    if not conn.execute(text("SELECT 1 FROM quotation WHERE kp_number = :k"), {"k": kp}).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "KP topilmadi")
    revisions = conn.execute(text("SELECT delete_quotation(:k)"), {"k": kp}).scalar_one()
    return {"ok": True, "kp_number": kp, "deleted_revisions": revisions}
