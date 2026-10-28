"""Joriy foydalanuvchi va ruxsat tekshiruvi."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .config import settings
from .db import get_conn, set_actor
from .guard import MFA_ROLES
from .security import token_hash


@dataclass
class CurrentUser:
    id: int
    login: str
    full_name: str
    employee_id: int
    access_valid_until: str | None
    roles: list[str]
    permissions: set[str]
    mfa_enabled: bool = False
    session_hash: str | None = None
    telegram_name: str | None = None     # ulangan Telegram (@username) — 2 bosqichli kirish
    admin_word_set: bool = False         # admin paneli uchun maxfiy so'z o'rnatilganmi
    admin_unlocked: bool = False         # shu sessiyada maxfiy so'z kiritilgan va muddati o'tmagan

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def as_dict(self) -> dict:
        return {"id": self.id, "login": self.login, "full_name": self.full_name, "employee_id": self.employee_id,
                "access_valid_until": self.access_valid_until, "roles": self.roles,
                "permissions": sorted(self.permissions), "mfa_enabled": self.mfa_enabled, "telegram_name": self.telegram_name,
                # admin/direktor uchun 2 bosqichli kirish yoqilmagan bo'lsa — interfeys qizil ogohlantirish ko'rsatadi
                "mfa_setup_required": not self.mfa_enabled and any(r in MFA_ROLES for r in self.roles),
                "admin_word_set": self.admin_word_set, "admin_unlocked": self.admin_unlocked}


def load_user(conn: Connection, user_id: int) -> CurrentUser | None:
    """Faqat faol va muddati o'tmagan foydalanuvchi (v_active_user)."""
    u = conn.execute(text(
        """SELECT a.user_id, a.login, a.full_name, u.employee_id, a.access_valid_until, u.telegram_chat_id IS NOT NULL AS mfa, u.telegram_name,
                  u.admin_word_hash IS NOT NULL AS aw
           FROM v_active_user a JOIN app_user u ON u.id = a.user_id WHERE a.user_id = :id"""), {"id": user_id}).first()
    if u is None:
        return None
    roles = [r[0] for r in conn.execute(text("SELECT role_code FROM user_role WHERE user_id = :id ORDER BY 1"), {"id": user_id})]
    perms = {r[0] for r in conn.execute(
        text("SELECT permission_code FROM v_user_effective_permission WHERE user_id = :id"), {"id": user_id})}
    return CurrentUser(u.user_id, u.login, u.full_name, u.employee_id,
                       u.access_valid_until.isoformat() if u.access_valid_until else None, roles, perms, bool(u.mfa), telegram_name=u.telegram_name, admin_word_set=bool(u.aw))


def _token(request: Request) -> str | None:
    token = request.cookies.get(settings().cookie_name)
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.lower().startswith("bearer ") else None


def current_user(request: Request, conn: Connection = Depends(get_conn, scope="function")) -> CurrentUser:
    """Sessiya bazada: bekor qilinmagan, muddati (access_token_hours) va harakatsizlik (session_idle_minutes) o'tmagan."""
    token = _token(request)
    sess = None
    if token:
        sess = conn.execute(text(
            """SELECT id, user_id, token_hash, last_seen_at < now() - interval '1 minute' AS stale,
                      coalesce(admin_unlocked_at > now() - make_interval(mins => :aidle), false) AS unlocked FROM user_session
               WHERE token_hash = :h AND revoked_at IS NULL AND expires_at > now()
                 AND last_seen_at > now() - make_interval(mins => :idle)"""),
            {"h": token_hash(token), "idle": settings().session_idle_minutes,
             "aidle": settings().admin_unlock_minutes}).first()
    user = load_user(conn, sess.user_id) if sess else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tizimga kirish talab qilinadi (yoki muddat tugagan)")
    if sess.stale:
        conn.execute(text("UPDATE user_session SET last_seen_at = now() WHERE id = :i"), {"i": sess.id})
    user.session_hash = sess.token_hash
    user.admin_unlocked = bool(sess.unlocked) and user.admin_word_set
    set_actor(conn, user.id)
    return user


def require(*any_of: str):
    """Kamida bitta ruxsat bo'lishi shart."""
    def checker(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not any(user.can(p) for p in any_of):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu amal uchun ruxsat yo'q: " + " yoki ".join(any_of))
        return user
    return checker


_admin = require("user.manage")


def require_admin_unlocked(user: CurrentUser = Depends(_admin),
                           conn: Connection = Depends(get_conn, scope="function")) -> CurrentUser:
    """Admin paneli: user.manage + shu sessiyada maxfiy so'z kiritilgan (admin_unlock_minutes harakatsizlikkacha)."""
    if not user.admin_word_set:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "admin_word_setup",
                            "message": "Admin paneli uchun avval maxfiy so'z o'rnating"})
    if not user.admin_unlocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "admin_word_required",
                            "message": "Admin paneli uchun maxfiy so'zni kiriting"})
    conn.execute(text("""UPDATE user_session SET admin_unlocked_at = now()
                         WHERE token_hash = :h AND admin_unlocked_at < now() - interval '1 minute'"""), {"h": user.session_hash})
    return user
