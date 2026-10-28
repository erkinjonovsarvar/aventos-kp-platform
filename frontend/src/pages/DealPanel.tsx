import { useEffect, useState } from "react";
import { api, dateUz, money } from "../api";

interface Ev { id: number; status_code: string; status_name: string; sold_amount: string | null; sold_currency: string | null; sold_on: string | null;
  lost_reason_name: string | null; comment: string | null; created_at: string; created_by_name: string }
interface Deal { current: Ev | null; history: Ev[]; can_update: boolean; suggested_amount: string | null; currency: string; needs_status: boolean }
interface Meta { statuses: { code: string; name: string }[]; lost_reasons: { code: string; name: string }[] }

const LOOK: Record<string, { icon: string; cls: string }> = {
  in_progress: { icon: "◔", cls: "st-progress" }, won: { icon: "✓", cls: "st-won" }, lost: { icon: "✕", cls: "st-lost" },
  closed: { icon: "■", cls: "st-closed" }, unset: { icon: "!", cls: "st-unset" },
};

/** Savdo holati belgisi (ikonka + nom — rang yolg'iz ma'no tashimaydi). */
export function DealPill({ code, name, soft }: { code: string | null | undefined; name?: string | null; soft?: boolean }) {
  const l = LOOK[code ?? "unset"] ?? LOOK.unset;
  // soft: yangi KP — hali belgilanmagani tabiiy, ko'zni charchatmasin (kulrang); eskisi — sariq (UX audit 9-band)
  return <span className={"deal-pill" + (soft ? " soft" : "")} title={soft ? "Hali belgilanmagan (yangi KP)" : undefined}>
    <span className={"chip-st " + (soft ? "st-soft" : l.cls)}>{soft ? "·" : l.icon}</span>{code ? name : "Belgilanmagan"}</span>;
}

const today = () => { const t = new Date(); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };

/** KP sahifasidagi "Savdo holati": menejer o'z KP siga belgilaydi, tarix pastda. */
export default function DealPanel({ kp }: { kp: number }) {
  const [d, setD] = useState<Deal | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [st, setSt] = useState("");
  const [amount, setAmount] = useState("");
  const [soldOn, setSoldOn] = useState(today());
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  const load = () => api.get<Deal>(`/api/quotations/${kp}/deal`).then(setD).catch(() => setD(null));
  useEffect(() => { void load(); api.get<Meta>("/api/deal/meta").then(setMeta).catch(() => undefined); }, [kp]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return null;

  function pick(code: string) {
    setSt(code); setError("");
    if (code === "won" && !amount) setAmount(d?.suggested_amount ? String(Math.round(Number(d.suggested_amount) * 100) / 100) : "");
  }
  const valid = st === "won" ? /^\d+([.,]\d+)?$/.test(amount.trim()) && Number(amount.replace(",", ".")) > 0 && !!soldOn
    : st === "lost" ? !!reason && !!comment.trim() : !!st;

  async function save() {
    setBusy(true); setError("");
    try {
      await api.post(`/api/quotations/${kp}/deal`, {
        status: st, comment: comment.trim() || null,
        ...(st === "won" ? { sold_amount: amount.trim().replace(",", "."), sold_on: soldOn } : {}),
        ...(st === "lost" ? { lost_reason: reason } : {}),
      });
      setSt(""); setComment(""); setReason(""); setOpen(false);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const c = d.current;
  return (
    <div className="panel">
      <div className="section-head">
        <h2>Savdo holati</h2>
        <DealPill code={c?.status_code} name={c?.status_name} />
      </div>
      {d.needs_status && d.can_update && (
        <div className="reminder" style={{ marginTop: 6 }}>
          <span>🔔</span><span>Iltimos, bu KP ning savdo holatini belgilang — bu sizning hisobotingiz uchun kerak.</span>
        </div>
      )}
      {c && (
        <p className="muted" style={{ margin: "4px 0 0" }}>
          {c.status_code === "won" && <>Sotildi: <b className="ink">{money(c.sold_amount, c.sold_currency ?? undefined)} {c.sold_currency}</b>, {dateUz(c.sold_on)}. </>}
          {c.status_code === "lost" && <>Sabab: <b className="ink">{c.lost_reason_name}</b>. </>}
          {c.comment && <>«{c.comment}» </>}
          — {c.created_by_name}, {dateUz(c.created_at.slice(0, 10))}
        </p>
      )}
      {d.can_update && !open && (
        <button className={d.needs_status ? "accent" : "secondary"} style={{ marginTop: 10 }} onClick={() => setOpen(true)}>
          {c ? "Holatni o'zgartirish" : "Holat belgilash"}
        </button>
      )}
      {d.can_update && open && meta && (
        <>
          <div className="seg" style={{ marginTop: 10 }}>
            {meta.statuses.map((s) => (
              <button key={s.code} className={st === s.code ? "on" : ""} onClick={() => pick(s.code)}>{LOOK[s.code]?.icon} {s.name}</button>
            ))}
          </div>
          {st && (
            <div className="deal-form">
              {st === "won" && (
                <>
                  <label>Sotilgan summa ({d.currency}, QQS bilan)<input value={amount} onChange={(e) => setAmount(e.target.value)} size={14} autoFocus /></label>
                  <label>Sotilgan sana<input type="date" value={soldOn} max={today()} onChange={(e) => setSoldOn(e.target.value)} /></label>
                </>
              )}
              {st === "lost" && (
                <label>Sabab
                  <select value={reason} onChange={(e) => setReason(e.target.value)}>
                    <option value="">— tanlang —</option>
                    {meta.lost_reasons.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
                  </select>
                </label>
              )}
              <label style={{ flex: 1, minWidth: 240 }}>{st === "lost" ? "Izoh (majburiy): nima sababdan yutqazildi?" : "Izoh (ixtiyoriy)"}
                <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder={st === "lost" ? "masalan: raqobatchi 12% arzon berdi" : ""} />
              </label>
              <button disabled={!valid || busy} onClick={() => void save()}>{busy ? "Saqlanmoqda…" : "Saqlash"}</button>
              <button className="secondary" onClick={() => { setOpen(false); setSt(""); }}>Bekor</button>
            </div>
          )}
          {error && <div className="alert err" style={{ marginTop: 10 }}>{error}</div>}
        </>
      )}
      {d.history.length > 1 && (
        <details style={{ marginTop: 12 }}>
          <summary className="muted">Tarix ({d.history.length})</summary>
          <ul className="history">
            {d.history.map((h) => (
              <li key={h.id}>
                <DealPill code={h.status_code} name={h.status_name} />
                <span className="muted">
                  {dateUz(h.created_at.slice(0, 10))}, {h.created_by_name}
                  {h.status_code === "won" && ` — ${money(h.sold_amount, h.sold_currency ?? undefined)} ${h.sold_currency}`}
                  {h.lost_reason_name && ` — ${h.lost_reason_name}`}{h.comment && ` — «${h.comment}»`}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
