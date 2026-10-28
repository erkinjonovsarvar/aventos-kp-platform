"""Chegirma isboti: skrinshot yoki PDF (foydalanuvchi talabi 2026-10-22, Alembic 0025).

Maqsad — chegirma o'zboshimcha berilmaganini isbotlash: fayl mahsulot (qator) yoki ilova chegirmasiga biriktiriladi.
- Yuklash: faqat admin (discount.manage). Ko'rish: discount.manage yoki discount.report_all, va KP ni ko'ra olishi kerak.
- Fayl bazada saqlanadi (zaxiraga kiradi), o'zgartirilmaydi va o'chirilmaydi (faqat KP butunlay o'chirilganda birga).
- Tasdiqlangan KP ga ham keyinroq qo'shish mumkin — narxga ta'siri yo'q.
- Faqat PNG / JPEG / WEBP / PDF (fayl ichidagi belgisi bo'yicha tekshiriladi, nomi bo'yicha emas), 10 MB gacha.
"""
import hashlib
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .. import kp_service as svc
from ..db import get_conn, rows
from ..deps import CurrentUser, require

router = APIRouter(prefix="/api", tags=["Chegirma isboti"])
MAX_BYTES = 10 * 1024 * 1024
VIEW = require("discount.manage", "discount.report_all")


def sniff(data: bytes) -> str | None:
    """Fayl turi ichidagi belgi (magic bytes) bo'yicha; boshqa tur — None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def clean_name(name: str | None, content_type: str) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", base).strip()[:200]
    return base or ("skrinshot" + {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(content_type, ".pdf"))


def _quotation_id(conn: Connection, kp: int, user: CurrentUser) -> int:
    svc.revision_for(conn, kp, user=user)                       # KP ni ko'ra olmasa — 404
    return conn.execute(text("SELECT id FROM quotation WHERE kp_number = :k"), {"k": kp}).scalar_one()


@router.post("/quotations/{kp}/evidence")
async def upload_evidence(kp: int, file: UploadFile = File(...),
                          line_id: int | None = Query(None), annex_id: int | None = Query(None),
                          user: CurrentUser = Depends(require("discount.manage")),
                          conn: Connection = Depends(get_conn, scope="function")):
    if (line_id is None) == (annex_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Isbot qator (line_id) yoki ilova (annex_id) chegirmasiga biriktiriladi")
    qid = _quotation_id(conn, kp, user)
    owner = conn.execute(text(
        """SELECT 1 FROM quotation_annex a JOIN quotation_revision r ON r.id = a.revision_id
           LEFT JOIN quotation_line l ON l.annex_id = a.id
           WHERE r.quotation_id = :q AND (a.id = :a OR l.id = :l) LIMIT 1"""), {"q": qid, "a": annex_id, "l": line_id}).first()
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Qator yoki ilova bu KP da topilmadi")
    data = await file.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Fayl bo'sh")
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Fayl 10 MB dan katta")
    ctype = sniff(data)
    if ctype is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Faqat rasm (PNG, JPEG, WEBP) yoki PDF fayl")
    sha = hashlib.sha256(data).hexdigest().upper()
    eid = conn.execute(text("SELECT id FROM discount_evidence WHERE quotation_id = :q AND sha256 = :h"), {"q": qid, "h": sha}).scalar()
    if eid is None:                                           # bir xil fayl ikki marta saqlanmaydi — faqat yangi bog'lanish
        eid = conn.execute(text(
            """INSERT INTO discount_evidence (quotation_id, file_name, content_type, size_bytes, sha256, data, uploaded_by)
               VALUES (:q, :n, :t, :s, :h, :d, :u) RETURNING id"""),
            {"q": qid, "n": clean_name(file.filename, ctype), "t": ctype, "s": len(data), "h": sha, "d": data, "u": user.id}).scalar_one()
    conn.execute(text(
        """INSERT INTO discount_evidence_link (evidence_id, line_id, annex_id, created_by)
           SELECT :e, :l, :a, :u WHERE NOT EXISTS (
               SELECT 1 FROM discount_evidence_link WHERE evidence_id = :e
                 AND line_id IS NOT DISTINCT FROM CAST(:l AS bigint) AND annex_id IS NOT DISTINCT FROM CAST(:a AS bigint))"""),
        {"e": eid, "l": line_id, "a": annex_id, "u": user.id})
    return {"id": eid, "content_type": ctype, "size_bytes": len(data)}


@router.get("/quotations/{kp}/evidence")
def list_evidence(kp: int, user: CurrentUser = Depends(VIEW), conn: Connection = Depends(get_conn, scope="function")):
    """KP ning barcha isbotlari (barcha revisionlar) va qaysi qator/ilovaga biriktirilgani."""
    qid = _quotation_id(conn, kp, user)
    return rows(conn.execute(text(
        """SELECT e.id, e.file_name, e.content_type, e.size_bytes, e.uploaded_at, emp.full_name AS uploaded_by_name,
                  coalesce(array_agg(k.line_id) FILTER (WHERE k.line_id IS NOT NULL), '{}') AS line_ids,
                  coalesce(array_agg(k.annex_id) FILTER (WHERE k.annex_id IS NOT NULL), '{}') AS annex_ids
           FROM discount_evidence e
           JOIN app_user u ON u.id = e.uploaded_by JOIN employee emp ON emp.id = u.employee_id
           LEFT JOIN discount_evidence_link k ON k.evidence_id = e.id
           WHERE e.quotation_id = :q
           GROUP BY e.id, emp.full_name ORDER BY e.id"""), {"q": qid}))


@router.get("/quotations/{kp}/evidence/{evidence_id}/file")
def evidence_file(kp: int, evidence_id: int, user: CurrentUser = Depends(VIEW),
                  conn: Connection = Depends(get_conn, scope="function")):
    qid = _quotation_id(conn, kp, user)
    e = conn.execute(text("SELECT file_name, content_type, data FROM discount_evidence WHERE id = :i AND quotation_id = :q"),
                     {"i": evidence_id, "q": qid}).first()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fayl topilmadi")
    ascii_name = "".join(ch if ord(ch) < 128 and ch not in '";\\' else "_" for ch in e.file_name)
    return Response(bytes(e.data), media_type=e.content_type,
                    headers={"Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(e.file_name)}"})
