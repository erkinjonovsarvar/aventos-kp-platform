import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api";

interface Ev { at: string; event: string; login: string | null; ip: string | null; user_agent: string | null; details: string | null; full_name: string | null }
interface Data { items: Ev[]; summary: { event: string; count: number; ips: number }[] }

export const EVENT_UZ: Record<string, { t: string; cls: string }> = {
  login_ok: { t: "Kirdi", cls: "ok" }, login_failed: { t: "Noto'g'ri parol", cls: "warn" }, login_locked: { t: "Login bloklandi", cls: "err" },
  ip_blocked: { t: "IP bloklandi", cls: "err" }, mfa_required: { t: "Kod yuborildi", cls: "" }, mfa_failed: { t: "Noto'g'ri kod", cls: "warn" },
  logout: { t: "Chiqdi", cls: "" }, session_expired: { t: "Sessiya tugadi", cls: "" }, sessions_revoked: { t: "Chiqarib yuborildi", cls: "warn" },
  mfa_enabled: { t: "Telegram ulandi", cls: "ok" }, mfa_disabled: { t: "Telegram uzildi", cls: "warn" }, mfa_reset: { t: "Telegram uzildi (admin)", cls: "warn" },
  admin_word_set: { t: "Maxfiy so'z o'rnatildi", cls: "ok" }, admin_word_ok: { t: "Admin paneli ochildi", cls: "" },
  admin_word_failed: { t: "Noto'g'ri maxfiy so'z", cls: "warn" }, admin_word_locked: { t: "Maxfiy so'z bloki", cls: "err" },
  join_invalid: { t: "Noto'g'ri taklif havolasi", cls: "warn" }, join_submitted: { t: "Kirish so'rovi", cls: "" }, join_blocked: { t: "Havola urinishi bloklandi", cls: "err" },
};
const ALERT = new Set(["login_locked", "ip_blocked", "join_blocked", "mfa_failed", "login_failed", "admin_word_failed", "admin_word_locked"]);

/** Admin: xavfsizlik jurnali — kim, qachon, qayerdan kirdi yoki kirmoqchi bo'ldi. */
export default function SecurityLog() {
  const [days, setDays] = useState(7);
  const [event, setEvent] = useState("");
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get<Data>("/api/admin/security-events" + qs({ days, event: event || undefined })).then(setD).catch((e) => setError(e.message));
  }, [days, event]);
  const alerts = d ? d.summary.filter((s) => ALERT.has(s.event)).reduce((a, s) => a + s.count, 0) : 0;
  return (
    <>
      <div className="breadcrumb"><Link to="/">Bosh sahifa</Link> / <b>Xavfsizlik jurnali</b></div>
      <h1>Xavfsizlik jurnali</h1>
      {error && <div className="alert err">{error}</div>}
      <div className="panel filterbar">
        <div className="seg">{[1, 7, 30, 90].map((n) => <button key={n} className={days === n ? "on" : ""} onClick={() => setDays(n)}>{n === 1 ? "Bugun" : `${n} kun`}</button>)}</div>
        <label>Hodisa
          <select value={event} onChange={(e) => setEvent(e.target.value)}>
            <option value="">— hammasi —</option>
            {Object.entries(EVENT_UZ).map(([k, v]) => <option key={k} value={k}>{v.t}</option>)}
          </select>
        </label>
      </div>
      {d && (
        <>
          <div className="kpis">
            <div className={"kpi" + (alerts ? " warn" : " good")}><span className="kpi-label">Shubhali urinishlar</span><b className="kpi-value">{alerts}</b>
              <span className="kpi-sub">noto'g'ri parol/kod va bloklar</span></div>
            {d.summary.filter((s) => !ALERT.has(s.event)).slice(0, 4).map((s) => (
              <div className="kpi" key={s.event}><span className="kpi-label">{EVENT_UZ[s.event]?.t ?? s.event}</span><b className="kpi-value">{s.count}</b>
                <span className="kpi-sub">{s.ips} ta IP manzil</span></div>
            ))}
          </div>
          <div className="panel table-wrap">
            <table className="compact">
              <thead><tr><th>Vaqt</th><th>Hodisa</th><th>Login / xodim</th><th>IP</th><th>Tafsilot</th></tr></thead>
              <tbody>
                {d.items.map((e, i) => (
                  <tr key={i}>
                    <td style={{ whiteSpace: "nowrap" }}>{new Date(e.at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "medium" })}</td>
                    <td><span className={"badge " + (EVENT_UZ[e.event]?.cls ?? "")}>{EVENT_UZ[e.event]?.t ?? e.event}</span></td>
                    <td>{e.full_name ?? e.login ?? "—"}{e.full_name && e.login ? <span className="muted"> ({e.login})</span> : null}</td>
                    <td className="mono">{e.ip}</td>
                    <td className="muted">{e.details}</td>
                  </tr>
                ))}
                {d.items.length === 0 && <tr><td colSpan={5} className="muted">Bu davrda hodisa yo'q.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
