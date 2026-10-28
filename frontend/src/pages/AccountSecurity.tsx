import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { toast } from "../toast";
import { useAuth } from "../auth";

interface Sess { id: number; created_at: string; last_seen_at: string; ip: string | null; user_agent: string | null; current: boolean }

const when = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
function device(ua: string | null) {
  if (!ua) return "Noma'lum qurilma";
  const os = /Android/i.test(ua) ? "Android" : /iPhone|iPad/i.test(ua) ? "iPhone/iPad" : /Windows/i.test(ua) ? "Windows" : /Mac OS/i.test(ua) ? "Mac" : "Boshqa";
  const br = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "brauzer";
  return `${os} · ${br}`;
}

/** Foydalanuvchining o'z xavfsizligi: Telegram orqali tasdiqlash va faol sessiyalar. */
export default function AccountSecurity() {
  const { user, refresh, logout } = useAuth();
  const [link, setLink] = useState<{ url: string; bot: string; minutes: number } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [sessions, setSessions] = useState<Sess[]>([]);
  const [msg, setMsg] = useState("");
  useEffect(() => { if (msg) { toast(msg); setMsg(""); } }, [msg]);   // 17: qalqib chiquvchi xabar
  const [error, setError] = useState("");

  const loadSessions = () => api.get<Sess[]>("/api/auth/sessions").then(setSessions).catch(() => undefined);
  useEffect(() => { void loadSessions(); }, []);
  const enabledNow = !!user?.mfa_enabled;
  // ulash havolasi ochilgach — bot javob berguncha har 3 soniyada tekshirish (10 daqiqagacha)
  useEffect(() => {
    if (!link || enabledNow) { if (enabledNow && link) { setLink(null); setMsg("✅ Telegram ulandi. Endi kirishda kod Telegram'ga keladi."); } return; }
    const started = Date.now();
    const t = window.setInterval(() => {
      if (Date.now() - started > link.minutes * 60_000) { window.clearInterval(t); setLink(null); return; }
      void refresh().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(t);
  }, [link, enabledNow, refresh]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setError(""); setMsg("");
    try { await fn(); setMsg(ok); } catch (e) { setError((e as Error).message); }
  }

  const enabled = !!user?.mfa_enabled;
  return (
    <>
      <div className="breadcrumb"><Link to="/">Bosh sahifa</Link> / <b>Xavfsizlik</b></div>
      <h1>Xavfsizlik</h1>
      {error && <div className="alert err">{error}</div>}

      <div className="panel">
        <div className="section-head">
          <h2>Telegram orqali tasdiqlash</h2>
          <span className={"badge " + (enabled ? "ok" : user?.mfa_setup_required ? "err" : "warn")}>
            {enabled ? `✓ Ulangan: ${user?.telegram_name ?? ""}` : "Ulanmagan"}</span>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          Parol o'g'irlansa ham hisobingizga kirib bo'lmaydi: har kirishda Telegram'ingizga 6 xonali kod keladi.
          Har yangi kirish haqida ham Telegram'ga xabar keladi.
          {user?.mfa_setup_required && <b style={{ color: "var(--err)" }}> Admin va direktor uchun majburiy.</b>}
        </p>

        {!enabled && !link && (
          <button onClick={() => void run(async () => {
            const r = await api.post<{ url: string; bot: string; minutes: number }>("/api/auth/telegram/link");
            setLink(r); window.open(r.url, "_blank", "noopener");
          }, "")}>✈ Telegram'ni ulash</button>
        )}

        {!enabled && link && (
          <ol className="steps-list">
            <li>Telegram ochildi — <b>@{link.bot}</b> botida <b>«Start» (Запустить)</b> tugmasini bosing.
              <div className="muted">Ochilmagan bo'lsa: <a href={link.url} target="_blank" rel="noopener noreferrer">shu havolani bosing</a> (telefonda ham ochsa bo'ladi).</div>
            </li>
            <li>Bot «✅ Telegram ulandi» deb javob beradi — shu sahifa o'zi yangilanadi.
              <div className="muted">Havola {link.minutes} daqiqa amal qiladi. <span className="spinner-dot" /> kutilmoqda…</div>
            </li>
          </ol>
        )}

        {enabled && (
          <details>
            <summary className="muted">Uzish (tavsiya etilmaydi)</summary>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="secondary" onClick={() => void run(() => api.post("/api/auth/telegram/unlink-code"),
                "Kod Telegram'ga yuborildi")}>Telegram'ga kod yuborish</button>
              <label>Parol<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
              <label>Telegram'dagi kod<input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" size={8} /></label>
              <button className="danger" disabled={!password || code.length !== 6} onClick={() => void run(async () => {
                await api.post("/api/auth/telegram/unlink", { code, password }); setCode(""); setPassword(""); await refresh();
              }, "Telegram uzildi")}>Uzish</button>
            </div>
          </details>
        )}
      </div>

      {user?.permissions.includes("user.manage") && <AdminWordPanel />}

      <div className="panel table-wrap">
        <div className="section-head">
          <h2>Faol kirishlar</h2>
          <button className="danger small" onClick={() => {
            if (window.confirm("Barcha qurilmalardan (shu qurilma ham) chiqilsinmi?")) {
              void api.post("/api/auth/logout-all").then(() => logout());
            }
          }}>Barcha qurilmalardan chiqish</button>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>Tanimagan qurilma ko'rsangiz — darhol «Barcha qurilmalardan chiqish» ni bosing va parolni almashtirish uchun adminga ayting.
          Sessiya {`60`} daqiqa harakatsizlikdan keyin o'zi tugaydi.</p>
        <table className="compact">
          <thead><tr><th>Qurilma</th><th>IP</th><th>Kirgan</th><th>Oxirgi faollik</th><th></th></tr></thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id}>
                <td>{device(s.user_agent)}</td><td className="mono">{s.ip}</td><td>{when(s.created_at)}</td><td>{when(s.last_seen_at)}</td>
                <td>{s.current && <span className="badge teal">shu qurilma</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Admin paneli maxfiy so'zini almashtirish (eski so'z + parol bilan). */
function AdminWordPanel() {
  const { user, refresh } = useAuth();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [w1, setW1] = useState("");
  const [w2, setW2] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { if (msg) { toast(msg); setMsg(""); } }, [msg]);   // 17: qalqib chiquvchi xabar
  const [err, setErr] = useState("");
  if (!user?.admin_word_set) return null;          // birinchi o'rnatish — admin sahifasini ochganda
  async function save() {
    setMsg(""); setErr("");
    if (w1 !== w2) { setErr("Ikki yangi so'z bir xil emas"); return; }
    try {
      await api.post("/api/auth/admin-word/set", { password: pw, current_word: cur, word: w1 });
      setCur(""); setPw(""); setW1(""); setW2(""); setMsg("Maxfiy so'z almashtirildi"); await refresh();
    } catch (e) { setErr((e as Error).message); }
  }
  return (
    <div className="panel">
      <div className="section-head"><h2>Admin paneli maxfiy so'zi</h2><span className="badge ok">✓ o'rnatilgan</span></div>
      <p className="muted" style={{ marginTop: 0 }}>Admin sahifalarini ochishda so'raladi. Faqat siz bilasiz.</p>
      {err && <div className="alert err">{err}</div>}
      <details>
        <summary className="muted">Almashtirish</summary>
        <div className="row" style={{ marginTop: 10 }}>
          <label>Hozirgi so'z<input type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="off" /></label>
          <label>Parol<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></label>
          <label>Yangi so'z<input type="password" value={w1} onChange={(e) => setW1(e.target.value)} autoComplete="off" minLength={8} /></label>
          <label>Takrorlang<input type="password" value={w2} onChange={(e) => setW2(e.target.value)} autoComplete="off" /></label>
          <button disabled={!cur || !pw || w1.length < 8} onClick={() => void save()}>Saqlash</button>
        </div>
      </details>
    </div>
  );
}
