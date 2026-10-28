"""Narx ro'yxati: ko'rish (price.view) va platformaning o'zida yangilash (price.manage) — foydalanuvchi talabi 2026-10-22."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .. import price_admin
from ..db import get_conn, plain, rows
from ..deps import CurrentUser, require

router = APIRouter(prefix="/api/price-list", tags=["Narx ro'yxati"])
VIEW = require("price.view", "price.manage")
MANAGE = require("price.manage")


def _plain(obj):
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return plain(obj)


@router.get("/current")
def current(q: str | None = None, limit: int = Query(200, ge=1, le=2000), user: CurrentUser = Depends(VIEW),
            conn: Connection = Depends(get_conn, scope="function")):
    """Joriy katalog: har modelning eng so'nggi tasdiqlangan narxi (qidiruv: model, tavsif, brend, seriya)."""
    s = (q or "").strip() or None
    items = rows(conn.execute(text(
        """SELECT * FROM (
             SELECT DISTINCT ON (p.id) p.model, b.name AS brand, s.name AS series, i.description, i.capacity, i.capacity_unit,
                    i.price_excl_vat, i.price_incl_vat, pl.id AS price_list_id, pl.valid_from
             FROM price_list_item i JOIN price_list pl ON pl.id = i.price_list_id
             JOIN product p ON p.id = i.product_id JOIN product_series s ON s.id = p.series_id JOIN brand b ON b.id = s.brand_id
             WHERE pl.approved_at IS NOT NULL ORDER BY p.id, pl.valid_from DESC, pl.id DESC) c
           WHERE CAST(:s AS text) IS NULL OR c.model ILIKE '%' || :s || '%' OR c.description ILIKE '%' || :s || '%'
              OR c.brand ILIKE '%' || :s || '%' OR c.series ILIKE '%' || :s || '%'
           ORDER BY c.brand, c.series, c.model LIMIT :lim"""), {"s": s, "lim": limit}))
    total = conn.execute(text(
        """SELECT count(DISTINCT i.product_id) FROM price_list_item i JOIN price_list pl ON pl.id = i.price_list_id
           WHERE pl.approved_at IS NOT NULL""")).scalar()
    return {"items": items, "total": total}


@router.get("/versions")
def versions(user: CurrentUser = Depends(VIEW), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text(
        """SELECT pl.id, pl.name, pl.valid_from, pl.approved_at, e.full_name AS approved_by_name,
                  (SELECT count(*) FROM price_list_item i WHERE i.price_list_id = pl.id) AS items
           FROM price_list pl LEFT JOIN app_user u ON u.id = pl.approved_by LEFT JOIN employee e ON e.id = u.employee_id
           WHERE pl.approved_at IS NOT NULL ORDER BY pl.valid_from DESC, pl.id DESC LIMIT 50""")))


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=price_admin.MAX_TEXT)


class ItemIn(BaseModel):
    row: int = Field(1, ge=1)
    model: str | None = Field(None, max_length=300)
    description: str | None = Field(None, max_length=4000)
    capacity: str | None = Field(None, max_length=50)
    unit: str | None = Field(None, max_length=20)
    brand: str | None = Field(None, max_length=200)
    series: str | None = Field(None, max_length=200)
    price_excl_vat: str | None = Field(None, max_length=50)
    price_incl_vat: str | None = Field(None, max_length=50)


class ItemsIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=price_admin.MAX_ROWS)


class ApplyIn(ItemsIn):
    name: str | None = Field(None, max_length=200, description="Versiya nomi (bo'sh bo'lsa avtomatik)")
    source: str = Field("Platforma: Excel'dan ro'yxat", max_length=200)


@router.post("/changes/parse")
def parse_changes(body: ParseIn, user: CurrentUser = Depends(MANAGE), conn: Connection = Depends(get_conn, scope="function")):
    """Excel'dan nusxalangan ro'yxat -> tekshiruv natijasi (bazaga hech narsa yozilmaydi)."""
    p = price_admin.parse(body.text)
    return _plain({**price_admin.check(conn, p["items"]), "header": p["header"], "layout": p["layout"]})


@router.post("/changes/check")
def check_changes(body: ItemsIn, user: CurrentUser = Depends(MANAGE), conn: Connection = Depends(get_conn, scope="function")):
    """Forma (bitta mahsulot) yoki tahrirlangan qatorlar -> tekshiruv natijasi."""
    return _plain(price_admin.check(conn, [i.model_dump() for i in body.items]))


@router.post("/changes/apply")
def apply_changes(body: ApplyIn, user: CurrentUser = Depends(MANAGE), conn: Connection = Depends(get_conn, scope="function")):
    """Yangi tasdiqlangan versiya yaratish (server qatorlarni qayta tekshiradi)."""
    return _plain(price_admin.apply(conn, [i.model_dump() for i in body.items], user.id, body.name, body.source))
