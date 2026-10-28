import { Fragment, useCallback, useEffect, useState } from "react";
import { api, dateUz } from "../api";
import { useAuth } from "../auth";
import { toast } from "../toast";
import PermissionPicker from "./PermissionPicker";

interface U {
  id: number; login: string; full_name: string; is_active: boolean; access_valid_until: string | null;
  last_login_at: string | null; can_login: boolean; roles: string[]; extra_permissions: string[]; effective_permissions: string[];
  mfa_enabled: boolean; telegram_name: string | null; active_sessions: number;
}

function EditUser({ u, onDone }: { u: U; onDone: (msg: string) => void }) {
  const [until, setUntil] = useState(u.access_valid_until ?? "");
  const [active, setActive] = useState(u.is_active);
  const [roles, setRoles] = useState(u.roles);
  const [extra, setExtra] = useState(u.extra_permissions);
  const [error, setError] = useState("");

  async function save() {
    try {
      await api.patch(`/api/admin/users/${u.id}`, {
        is_active: active,
        access_valid_until: until || null,
        clear_access_valid_until: !until,
        roles,
        extra_permissions: extra,
      });
      onDone(`${u.full_name}: saqlandi`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="panel" style={{ background: "var(--panel-2)" }}>
      {error && <div className="alert err">{error}</div>}
      <div className="row" style={{ marginBottom: 12 }}>
        <label>Foydalanish muddati (bo'sh = muddatsiz)<input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 6, color: "inherit" }}>
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Faol
        </label>
      </div>
      <PermissionPicker roles={roles} extra={extra} onChange={(r, x) => { setRoles(r); setExtra(x); }} />
      <div className="row" style={{ marginTop: 12 }}><button onClick={() => void save()}>Saqlash</button></div>
    </div>
  );
}

export default function Users() {
  const { user } = useAuth();
  const [items, setItems] = useState<U[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { if (msg) { toast(msg); setMsg(""); } }, [msg]);   // 17: qalqib chiquvchi xabar

  const load = useCallback(() => { api.get<U[]>("/api/admin/users").then(setItems).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);
  function act(u: U, path: string, ask: string, done: string) {
    if (!window.confirm(ask)) return;
    setError(""); setMsg("");
    api.post(`/api/admin/users/${u.id}/${path}`).then(() => { setMsg(`${u.full_name}: ${done}`); load(); }).catch((e) => setError(e.message));
  }

  return (
    <>
      <h1>Foydalanuvchilar</h1>
      {error && <div className="alert err">{error}</div>}
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>F.I.Sh.</th><th>Login</th><th>Rol</th><th>Muddat</th><th>Holat</th><th>Telegram</th><th className="num">Sessiya</th><th>Oxirgi kirish</th><th className="num">Ruxsatlar</th><th></th></tr></thead>
          <tbody>
            {items.map((u) => (
              <Fragment key={u.id}>
                <tr>
                  <td>{u.full_name}{u.id === user?.id && <span className="muted"> (siz)</span>}</td>
                  <td>{u.login}</td>
                  <td>{u.roles.join(", ")}</td>
                  <td>{u.access_valid_until ? dateUz(u.access_valid_until) : "muddatsiz"}</td>
                  <td>{u.can_login ? <span className="badge ok">kira oladi</span> : <span className="badge err">kira olmaydi</span>}</td>
                  <td>{u.mfa_enabled ? <span className="badge ok" title={u.telegram_name ?? ""}>✓ ulangan</span> : <span className="muted">—</span>}</td>
                  <td className="num">{u.active_sessions}</td>
                  <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString("ru-RU") : "—"}</td>
                  <td className="num" title={u.effective_permissions.join("\n")}>{u.effective_permissions.length}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="secondary" onClick={() => setOpen(open === u.id ? null : u.id)}>{open === u.id ? "Yopish" : "O'zgartirish"}</button>
                    {u.id !== user?.id && u.active_sessions > 0 && (
                      <button className="secondary small" style={{ marginLeft: 6 }} title="Barcha qurilmalardagi kirishlarini yopish"
                              onClick={() => act(u, "revoke-sessions", `${u.full_name} barcha qurilmalardan chiqarib yuborilsinmi?`, "chiqarib yuborildi")}>
                        Chiqarib yuborish</button>
                    )}
                    {u.id !== user?.id && u.mfa_enabled && (
                      <button className="secondary small" style={{ marginLeft: 6 }} title="Telefoni/Telegram'i yo'qolgan bo'lsa"
                              onClick={() => act(u, "reset-2fa", `${u.full_name} ning Telegram'i uzilsinmi? U qayta ulashi kerak bo'ladi.`, "Telegram uzildi")}>
                        Telegram'ni uzish</button>
                    )}
                  </td>
                </tr>
                {open === u.id && (
                  <tr><td colSpan={10}><EditUser u={u} onDone={(m) => { setOpen(null); setMsg(m); load(); }} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
