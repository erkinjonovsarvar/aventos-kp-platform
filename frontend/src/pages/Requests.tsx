import { useCallback, useEffect, useState } from "react";
import { api, qs } from "../api";
import { toast } from "../toast";
import PermissionPicker from "./PermissionPicker";

interface Req {
  id: number; full_name: string; phone: string; email: string | null; position: string | null;
  requested_at: string; status: string; review_note: string | null; invitation_note: string | null; created_login: string | null;
}
interface Employee { id: number; full_name: string; phone: string | null; is_active: boolean; has_login: boolean; kp_count: string }

function ApproveForm({ req, onDone }: { req: Req; onDone: () => void }) {
  const [login, setLogin] = useState("");
  const [until, setUntil] = useState("");
  const [roles, setRoles] = useState<string[]>(["manager"]);
  const [extra, setExtra] = useState<string[]>([]);
  const [employeeId, setEmployeeId] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [error, setError] = useState("");

  useEffect(() => { api.get<Employee[]>("/api/admin/employees").then(setEmployees).catch(() => undefined); }, []);
  const free = employees.filter((e) => e.is_active && !e.has_login);

  async function approve() {
    try {
      await api.post(`/api/admin/access-requests/${req.id}/approve`, {
        login: login.trim(), access_valid_until: until || null, roles, extra_permissions: extra,
        employee_id: employeeId ? Number(employeeId) : null,
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="panel" style={{ background: "var(--panel-2)" }}>
      {error && <div className="alert err">{error}</div>}
      <div className="row" style={{ marginBottom: 12 }}>
        <label>Login (tizimga kirish nomi)<input value={login} onChange={(e) => setLogin(e.target.value)} required /></label>
        <label>Foydalanish muddati (bo'sh = muddatsiz)<input type="date" value={until} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setUntil(e.target.value)} /></label>
        <label>
          Mavjud menejerga bog'lash (o'z KP larini ko'radi)
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">— yangi xodim sifatida —</option>
            {free.map((e) => <option key={e.id} value={e.id}>{e.full_name} ({e.kp_count} KP)</option>)}
          </select>
        </label>
      </div>
      <PermissionPicker roles={roles} extra={extra} onChange={(r, x) => { setRoles(r); setExtra(x); }} />
      <div className="row" style={{ marginTop: 12 }}>
        <button disabled={login.trim().length < 3} onClick={() => void approve()}>Tasdiqlash</button>
      </div>
    </div>
  );
}

export default function Requests() {
  const [status, setStatus] = useState("pending");
  const [items, setItems] = useState<Req[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { if (msg) { toast(msg); setMsg(""); } }, [msg]);   // 17: qalqib chiquvchi xabar

  const load = useCallback(() => {
    api.get<Req[]>("/api/admin/access-requests" + qs({ status_: status || undefined })).then(setItems).catch((e) => setError(e.message));
  }, [status]);
  useEffect(load, [load]);

  async function reject(id: number) {
    const note = window.prompt("Rad etish sababi (ixtiyoriy):") ?? undefined;
    try {
      await api.post(`/api/admin/access-requests/${id}/reject`, { note: note || null });
      setMsg("So'rov rad etildi");
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <h1>Kirish so'rovlari</h1>
      <div className="filters">
        <label>Holat
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="pending">Kutilmoqda</option><option value="approved">Tasdiqlangan</option>
            <option value="rejected">Rad etilgan</option><option value="">Hammasi</option>
          </select>
        </label>
      </div>
      {error && <div className="alert err">{error}</div>}
      {items.length === 0 && <div className="panel muted">So'rovlar yo'q. Yangi xodim uchun "Havolalar" bo'limida havola yarating.</div>}
      {items.map((r) => (
        <div className="panel" key={r.id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <b>{r.full_name}</b> — {r.phone}{r.email ? `, ${r.email}` : ""}{r.position ? `, ${r.position}` : ""}
              <div className="muted">
                {new Date(r.requested_at).toLocaleString("ru-RU")}{r.invitation_note ? ` · havola: ${r.invitation_note}` : ""}
                {r.created_login ? ` · login: ${r.created_login}` : ""}{r.review_note ? ` · ${r.review_note}` : ""}
              </div>
            </div>
            {r.status === "pending" && (
              <div className="row">
                <button onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "Yopish" : "Tasdiqlash…"}</button>
                <button className="danger" onClick={() => void reject(r.id)}>Rad etish</button>
              </div>
            )}
          </div>
          {open === r.id && <ApproveForm req={r} onDone={() => { setOpen(null); setMsg(`${r.full_name} tasdiqlandi`); load(); }} />}
        </div>
      ))}
    </>
  );
}
