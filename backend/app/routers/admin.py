"""Foydalanuvchilarni boshqarish: taklif havolasi → so'rov → tasdiqlash (muddat va ruxsatlar bilan)."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..config import settings
from ..db import get_conn, row, rows
from ..deps import CurrentUser, require_admin_unlocked
from ..guard import client_ip, join_blocked, log_event, revoke_sessions
from ..security import MIN_PASSWORD_LENGTH, hash_password, invitation_hash, new_invitation_token

admin = APIRouter(prefix="/api/admin", tags=["Admin: foydalanuvchilar"])
public = APIRouter(prefix="/api/join", tags=["Taklif havolasi (ochiq)"])
ADMIN = require_admin_unlocked          # user.manage + maxfiy so'z (foydalanuvchi talabi 2026-10-17)
ADMIN_ONLY = {"kp.delete"}          # foydalanuvchi talabi: KP ni faqat admin o'chiradi


# ------------------------------------------------------------------ taklif havolasi
class InvitationIn(BaseModel):
    note: str | None = Field(None, description="Kimga yuborilmoqda (masalan, ism)")
    valid_hours: int = Field(default_factory=lambda: settings().invitation_hours_default, ge=1, le=24 * 30)


@admin.post("/invitations")
def create_invitation(body: InvitationIn, request: Request, user: CurrentUser = Depends(ADMIN),
                      conn: Connection = Depends(get_conn, scope="function")):
    token, token_hash = new_invitation_token()
    inv = row(conn.execute(text(
        """INSERT INTO invitation (token_hash, created_by, expires_at, note)
           VALUES (:h, :u, now() + make_interval(hours => :hrs), :n) RETURNING id, created_at, expires_at, note"""),
        {"h": token_hash, "u": user.id, "hrs": body.valid_hours, "n": body.note}))
    base = settings().public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return {**inv, "link": f"{base}/join/{token}",
            "warning": "Havola faqat hozir ko'rsatiladi va bir marta ishlatiladi — saqlab qo'ying"}


@admin.get("/invitations")
def list_invitations(user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text(
        """SELECT i.id, i.note, i.created_at, i.expires_at, i.used_at,
                  CASE WHEN i.used_at IS NOT NULL THEN 'used' WHEN i.revoked_at IS NOT NULL THEN 'revoked'
                       WHEN i.expires_at < now() THEN 'expired' ELSE 'active' END AS state
           FROM invitation i ORDER BY i.id DESC""")))


@admin.post("/invitations/{inv_id}/revoke")
def revoke_invitation(inv_id: int, user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    """Ishlatilmagan havolani darhol bekor qilish."""
    r = row(conn.execute(text(
        """UPDATE invitation SET revoked_at = now()
           WHERE id = :i AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now() RETURNING id"""), {"i": inv_id}))
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faol havola topilmadi (ishlatilgan yoki muddati tugagan)")
    return {"ok": True}


INVALID_LINK = "Havola yaroqsiz, ishlatilgan yoki muddati tugagan"


def _invitation(conn: Connection, token: str):
    inv = conn.execute(text("SELECT id, expires_at, used_at, revoked_at FROM invitation WHERE token_hash = :h"),
                       {"h": invitation_hash(token)}).first()
    if inv is None or inv.used_at is not None or inv.revoked_at is not None or inv.expires_at < datetime.now(timezone.utc):
        return None
    return inv


def _join_guard(conn: Connection, request: Request, token: str):
    """(taklif, xato javob). Noto'g'ri token urinishlari jurnalga yoziladi; IP dan soatiga ko'p bo'lsa — blok.
    Xato javob exception emas, JSONResponse — jurnal yozuvi tranzaksiya bilan birga saqlansin."""
    if join_blocked(conn, client_ip(request)):
        log_event(conn, "join_blocked", request)
        return None, JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                  content={"detail": "Juda ko'p urinish — 1 soatdan keyin qayta urining"})
    inv = _invitation(conn, token)
    if inv is None:
        log_event(conn, "join_invalid", request, details=f"token {token[:6]}…")
        return None, JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": INVALID_LINK})
    return inv, None


@public.get("/{token}")
def check_invitation(token: str, request: Request, conn: Connection = Depends(get_conn, scope="function")):
    inv, err = _join_guard(conn, request, token)
    if err:
        return err
    return {"valid": True, "expires_at": inv.expires_at.isoformat()}


class AccessRequestIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    phone: str = Field(min_length=7, max_length=40)
    email: str | None = Field(None, max_length=120)
    position: str | None = Field(None, max_length=120)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)


@public.post("/{token}")
def submit_request(token: str, body: AccessRequestIn, request: Request, conn: Connection = Depends(get_conn, scope="function")):
    inv, err = _join_guard(conn, request, token)
    if err:
        return err
    conn.execute(text("UPDATE invitation SET used_at = now() WHERE id = :id"), {"id": inv.id})
    req = row(conn.execute(text(
        """INSERT INTO access_request (invitation_id, full_name, phone, email, position, password_hash)
           VALUES (:i, :f, :p, :e, :pos, :h) RETURNING id, requested_at, status"""),
        {"i": inv.id, "f": body.full_name.strip(), "p": body.phone.strip(), "e": body.email, "pos": body.position,
         "h": hash_password(body.password)}))
    log_event(conn, "join_submitted", request, login=body.full_name.strip(), details=f"so'rov {req['id']}")
    return {**req, "message": "So'rov yuborildi. Administrator tasdiqlagach tizimga kira olasiz."}


# ------------------------------------------------------------------ so'rovlar
@admin.get("/access-requests")
def list_requests(status_: str | None = "pending", user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    return rows(conn.execute(text(
        """SELECT r.id, r.full_name, r.phone, r.email, r.position, r.requested_at, r.status, r.reviewed_at, r.review_note,
                  i.note AS invitation_note, u.login AS created_login
           FROM access_request r JOIN invitation i ON i.id = r.invitation_id
           LEFT JOIN app_user u ON u.id = r.created_user_id
           WHERE CAST(:s AS text) IS NULL OR r.status = :s ORDER BY r.requested_at DESC"""), {"s": status_}))


class ApproveIn(BaseModel):
    login: str = Field(min_length=3)
    access_valid_until: date | None = Field(None, description="Foydalanish muddati (bo'sh = muddatsiz)")
    roles: list[str] = Field(default_factory=lambda: ["manager"])
    extra_permissions: list[str] = Field(default_factory=list)
    employee_id: int | None = Field(None, description="Mavjud menejer (KP larida ko'rsatilgan) bilan bog'lash")
    note: str | None = None


def _set_access(conn: Connection, admin_id: int, user_id: int, roles: list[str], perms: list[str]):
    known_roles = {r[0] for r in conn.execute(text("SELECT code FROM role"))}
    known_perms = {r[0] for r in conn.execute(text("SELECT code FROM permission"))}
    if bad := set(roles) - known_roles:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Noma'lum rol: {sorted(bad)}")
    if bad := set(perms) - known_perms:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Noma'lum ruxsat: {sorted(bad)}")
    if ADMIN_ONLY & set(perms):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Bu ruxsat faqat admin rolida bo'ladi, alohida berilmaydi: {sorted(ADMIN_ONLY & set(perms))}")
    conn.execute(text("DELETE FROM user_role WHERE user_id = :u"), {"u": user_id})
    conn.execute(text("DELETE FROM user_permission WHERE user_id = :u"), {"u": user_id})
    for r in roles:
        conn.execute(text("INSERT INTO user_role (user_id, role_code) VALUES (:u, :r)"), {"u": user_id, "r": r})
    for p in perms:
        conn.execute(text("INSERT INTO user_permission (user_id, permission_code, granted_by) VALUES (:u, :p, :a)"),
                     {"u": user_id, "p": p, "a": admin_id})


@admin.post("/access-requests/{request_id}/approve")
def approve(request_id: int, body: ApproveIn, user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    req = conn.execute(text("SELECT * FROM access_request WHERE id = :id AND status = 'pending' FOR UPDATE"),
                       {"id": request_id}).first()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kutilayotgan so'rov topilmadi")
    if conn.execute(text("SELECT 1 FROM app_user WHERE lower(login) = lower(:l)"), {"l": body.login}).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu login band")
    if body.access_valid_until and body.access_valid_until < date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Muddat o'tmishda bo'lishi mumkin emas")
    if body.employee_id:
        emp = conn.execute(text(
            """SELECT e.id FROM employee e WHERE e.id = :e AND e.is_active
               AND NOT EXISTS (SELECT 1 FROM app_user u WHERE u.employee_id = e.id)"""), {"e": body.employee_id}).first()
        if emp is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Xodim topilmadi, nofaol yoki allaqachon foydalanuvchiga bog'langan")
        employee_id = emp.id
    else:
        employee_id = conn.execute(text("INSERT INTO employee (full_name, phone) VALUES (:f, :p) RETURNING id"),
                                   {"f": req.full_name, "p": req.phone}).scalar_one()
    new_id = conn.execute(text(
        """INSERT INTO app_user (employee_id, login, password_hash, access_valid_until)
           VALUES (:e, :l, :h, :v) RETURNING id"""),
        {"e": employee_id, "l": body.login, "h": req.password_hash, "v": body.access_valid_until}).scalar_one()
    _set_access(conn, user.id, new_id, body.roles, body.extra_permissions)
    conn.execute(text(
        """UPDATE access_request SET status = 'approved', reviewed_by = :a, reviewed_at = now(), review_note = :n,
                  created_user_id = :u, password_hash = NULL WHERE id = :id"""),
        {"a": user.id, "n": body.note, "u": new_id, "id": request_id})
    return {"user_id": new_id, "login": body.login, "employee_id": employee_id,
            "access_valid_until": body.access_valid_until, "roles": body.roles, "extra_permissions": body.extra_permissions}


class RejectIn(BaseModel):
    note: str | None = None


@admin.post("/access-requests/{request_id}/reject")
def reject(request_id: int, body: RejectIn, user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    r = row(conn.execute(text(
        """UPDATE access_request SET status = 'rejected', reviewed_by = :a, reviewed_at = now(), review_note = :n,
                  password_hash = NULL WHERE id = :id AND status = 'pending' RETURNING id, status"""),
        {"a": user.id, "n": body.note, "id": request_id}))
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kutilayotgan so'rov topilmadi")
    return r


# ------------------------------------------------------------------ foydalanuvchilar
@admin.get("/users")
def list_users(user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    users = rows(conn.execute(text(
        """SELECT u.id, u.login, e.full_name, e.id AS employee_id, u.is_active, u.access_valid_until, u.last_login_at,
                  (u.is_active AND e.is_active AND (u.access_valid_until IS NULL OR u.access_valid_until >= current_date))
                    AS can_login,
                  u.telegram_chat_id IS NOT NULL AS mfa_enabled, u.telegram_name,
                  (SELECT count(*) FROM user_session s WHERE s.user_id = u.id AND s.revoked_at IS NULL AND s.expires_at > now()
                     AND s.last_seen_at > now() - make_interval(mins => :idle)) AS active_sessions
           FROM app_user u JOIN employee e ON e.id = u.employee_id ORDER BY e.full_name"""),
        {"idle": settings().session_idle_minutes}))
    roles = rows(conn.execute(text("SELECT user_id, role_code FROM user_role")))
    perms = rows(conn.execute(text("SELECT user_id, permission_code, granted_via FROM v_user_effective_permission")))
    extra = rows(conn.execute(text("SELECT user_id, permission_code FROM user_permission")))
    for u in users:
        u["roles"] = sorted(r["role_code"] for r in roles if r["user_id"] == u["id"])
        u["extra_permissions"] = sorted(p["permission_code"] for p in extra if p["user_id"] == u["id"])
        u["effective_permissions"] = sorted({p["permission_code"] for p in perms if p["user_id"] == u["id"]})
    return users


class UserUpdateIn(BaseModel):
    is_active: bool | None = None
    access_valid_until: date | None = None
    clear_access_valid_until: bool = Field(False, description="true — muddatsiz qilish")
    roles: list[str] | None = None
    extra_permissions: list[str] | None = None


@admin.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    target = conn.execute(text("SELECT id FROM app_user WHERE id = :id"), {"id": user_id}).first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    if user_id == user.id and (body.is_active is False or (body.roles is not None and "admin" not in body.roles)):
        raise HTTPException(status.HTTP_409_CONFLICT, "O'zingizni o'chira olmaysiz yoki admin rolidan chiqara olmaysiz")
    if body.is_active is not None:
        conn.execute(text("UPDATE app_user SET is_active = :v WHERE id = :id"), {"v": body.is_active, "id": user_id})
        if body.is_active is False:
            revoke_sessions(conn, user_id, "deactivated")
    if body.clear_access_valid_until:
        conn.execute(text("UPDATE app_user SET access_valid_until = NULL WHERE id = :id"), {"id": user_id})
    elif body.access_valid_until is not None:
        conn.execute(text("UPDATE app_user SET access_valid_until = :v WHERE id = :id"),
                     {"v": body.access_valid_until, "id": user_id})
    if body.roles is not None or body.extra_permissions is not None:
        cur_roles = [r[0] for r in conn.execute(text("SELECT role_code FROM user_role WHERE user_id = :u"), {"u": user_id})]
        cur_perms = [r[0] for r in conn.execute(text("SELECT permission_code FROM user_permission WHERE user_id = :u"), {"u": user_id})]
        _set_access(conn, user.id, user_id,
                    body.roles if body.roles is not None else cur_roles,
                    body.extra_permissions if body.extra_permissions is not None else cur_perms)
        if user_id != user.id:
            revoke_sessions(conn, user_id, "access_changed")          # yangi ruxsatlar bilan qayta kirsin
    return {"ok": True}


@admin.post("/users/{user_id}/revoke-sessions")
def admin_revoke_sessions(user_id: int, request: Request, user: CurrentUser = Depends(ADMIN),
                          conn: Connection = Depends(get_conn, scope="function")):
    """Foydalanuvchini barcha qurilmalardan chiqarish (telefon yo'qolsa, shubha bo'lsa)."""
    login = conn.execute(text("SELECT login FROM app_user WHERE id = :u"), {"u": user_id}).scalar()
    if login is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    n = revoke_sessions(conn, user_id, "admin", except_hash=user.session_hash if user_id == user.id else None)
    log_event(conn, "sessions_revoked", request, login=login, user_id=user_id, details=f"admin {user.login}: {n} ta sessiya")
    return {"ok": True, "revoked": n}


@admin.post("/users/{user_id}/reset-2fa")
def admin_reset_2fa(user_id: int, request: Request, user: CurrentUser = Depends(ADMIN),
                    conn: Connection = Depends(get_conn, scope="function")):
    """Telefon/Telegram yo'qolganda: Telegram'ni uzish (foydalanuvchi qayta ulaydi)."""
    if user_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "O'zingiznikini 'Xavfsizlik' sahifasida parol va kod bilan uzing")
    login = conn.execute(text("""UPDATE app_user SET telegram_chat_id = NULL, telegram_name = NULL, telegram_linked_at = NULL WHERE id = :u
                                 RETURNING login"""), {"u": user_id}).scalar()
    if login is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    revoke_sessions(conn, user_id, "mfa_reset")
    log_event(conn, "mfa_reset", request, login=login, user_id=user_id, details=f"admin {user.login}")
    return {"ok": True}


@admin.get("/security-events")
def security_events(event: str | None = None, days: int = Query(7, ge=1, le=365), limit: int = Query(300, ge=1, le=2000),
                    user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    """Xavfsizlik jurnali: kirish urinishlari, bloklar, 2FA, sessiyalar."""
    items = rows(conn.execute(text(
        """SELECT e.at, e.event, e.login, e.ip, e.user_agent, e.details, emp.full_name
           FROM auth_event e LEFT JOIN app_user u ON u.id = e.user_id LEFT JOIN employee emp ON emp.id = u.employee_id
           WHERE e.at > now() - make_interval(days => :d) AND (CAST(:ev AS text) IS NULL OR e.event = :ev)
           ORDER BY e.at DESC LIMIT :lim"""), {"d": days, "ev": event, "lim": limit}))
    summary = rows(conn.execute(text(
        """SELECT event, count(*) AS count, count(DISTINCT ip) AS ips FROM auth_event
           WHERE at > now() - make_interval(days => :d) GROUP BY event ORDER BY count(*) DESC"""), {"d": days}))
    return {"items": items, "summary": summary}


@admin.get("/permissions")
def list_permissions(user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    return {"permissions": rows(conn.execute(text("SELECT code, name FROM permission ORDER BY code"))),
            "roles": rows(conn.execute(text(
                """SELECT r.code, r.name, array_agg(rp.permission_code ORDER BY rp.permission_code) AS permissions
                   FROM role r LEFT JOIN role_permission rp ON rp.role_code = r.code GROUP BY r.code, r.name ORDER BY r.code""")))}


@admin.get("/employees")
def list_employees(user: CurrentUser = Depends(ADMIN), conn: Connection = Depends(get_conn, scope="function")):
    """Menejerlar — so'rovni tasdiqlashda mavjud xodimga bog'lash uchun."""
    return rows(conn.execute(text(
        """SELECT e.id, e.legacy_manager_id, e.full_name, e.phone, e.is_active,
                  EXISTS (SELECT 1 FROM app_user u WHERE u.employee_id = e.id) AS has_login,
                  (SELECT count(*) FROM quotation q WHERE q.manager_id = e.id) AS kp_count
           FROM employee e ORDER BY e.full_name""")))
