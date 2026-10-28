/** Sana oralig'i: tez tugmalar (Bugun / Bu hafta / Bu oy / Bu yil) + qo'lda tanlash (UX audit 2026-10-17, 13-band). */
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function preset(key: string): [string, string] {
  const t = new Date();
  if (key === "today") return [iso(t), iso(t)];
  if (key === "week") { const m = new Date(t); m.setDate(t.getDate() - ((t.getDay() + 6) % 7)); return [iso(m), iso(t)]; }
  if (key === "month") return [iso(new Date(t.getFullYear(), t.getMonth(), 1)), iso(t)];
  if (key === "year") return [iso(new Date(t.getFullYear(), 0, 1)), iso(t)];
  return ["", ""];
}

const PRESETS: [string, string][] = [["all", "Hammasi"], ["today", "Bugun"], ["week", "Bu hafta"], ["month", "Bu oy"], ["year", "Bu yil"]];

export default function DateRange({ from, to, onChange }: { from: string; to: string; onChange: (from: string, to: string) => void }) {
  const active = PRESETS.find(([k]) => { const [f, t] = preset(k); return f === from && t === to; })?.[0];
  return (
    <div className="date-range">
      <div className="seg" role="group" aria-label="Davr">
        {PRESETS.map(([k, label]) => (
          <button key={k} type="button" className={active === k ? "on" : ""} onClick={() => { const [f, t] = preset(k); onChange(f, t); }}>{label}</button>
        ))}
      </div>
      <label className="date-inline">dan<input type="date" value={from} onChange={(e) => onChange(e.target.value, to)} /></label>
      <label className="date-inline">gacha<input type="date" value={to} onChange={(e) => onChange(from, e.target.value)} /></label>
    </div>
  );
}
