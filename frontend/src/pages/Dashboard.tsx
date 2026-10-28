import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, dateUz, qs } from "../api";
import { useAuth } from "../auth";
import { DEAL_TRACKING } from "../features";

/* Dashboard (qayta loyiha 2026-10-22). Har bir vizual — bitta savolga javob, takrorsiz:
   KPI qatori      — "qancha va o'tgan davrga nisbatan qanday?"
   Dinamika        — "vaqt bo'yicha qanday o'zgardi?" (joriy davr ustunlari + taqqoslash davri chizig'i, bitta o'q)
   Kategoriyalar   — "summaning qaysi mahsulotlardan iborat?"
   Menejerlar      — "kim qancha KP berdi, o'rtacha hajmi va chegirmasi qanday?"
   Top loyihalar   — "qaysi loyihalarda eng katta summa?"
   KP hajmi        — "KP lar odatda qanday o'lchamda?"
   Chegirma        — "chegirma qanchalik chuqur va qaysi KP larda eng katta?" */

type Gran = "day" | "month" | "quarter" | "year";
type Num = string | null;
interface Bucket {
  start: string; label: string; kp_count: number; kp_sum_usd: string; won_count: number; won_sum_usd: string;
  prev_label: string | null; prev_kp_count: number | null; prev_kp_sum_usd: Num;
}
interface Summary {
  kp_count: number; kp_sum_usd: string; unpriced_count: number; avg_usd: Num; median_usd: Num; revised_count: number;
  discounted_count: number; discount_usd: string; discount_rate: Num; projects: number; new_projects: number; managers: number;
}
interface Manager {
  manager_id: number; manager_name: string; kp_count: number; kp_sum_usd: string; won_count: number; won_sum_usd: string;
  lost_count: number; unset_count: number; avg_usd: Num; share: Num; projects: number; discounted_count: number; discount_rate: Num;
}
interface Dash {
  period: { from: string; to: string; granularity: Gran; manager_id: number | null; scope: "all" | "own"; compare_from: string; compare_to: string };
  summary: Summary; previous: Summary;
  kpi: { kp_count: number; kp_sum_usd: string; unset_count: number; unset_sum_usd: string; won_count: number; won_sum_usd: string;
         avg_won_usd: Num; conversion: Num; decided_won: number; decided_lost: number };
  by_status: { code: string; name: string; count: number; sum_usd: string }[];
  lost_reasons: { name: string; count: number }[];
  series: Bucket[];
  managers: Manager[];
  categories: { name: string; kp_count: number; sum_usd: Num }[];
  projects: { project_id: number; project_name: string; kp_count: number; kp_sum_usd: string; managers: string[]; last_on: string; last_kp: number; is_new: boolean }[];
  sizes: { lo: number; hi: number | null; count: number; sum_usd: string }[];
  discounts: { buckets: { lo: string; hi: Num; count: number; discount_usd: string }[];
               top: { kp_number: number; project_name: string; manager_name: string; discount_usd: string; rate: string; total_usd: Num }[] };
  wins: { kp_number: number; project_name: string; manager_name: string; sold_on: string; sold_usd: Num; total_usd: Num }[];
  losses: { kp_number: number; project_name: string; manager_name: string; lost_reason_name: string; comment: string | null; total_usd: Num }[];
}

// Savdo holatlari — holat ranglari (ikonka + nom bilan, rang yolg'iz ma'no tashimaydi)
export const DEAL_LOOK: Record<string, { icon: string; cls: string }> = {
  in_progress: { icon: "◔", cls: "st-progress" }, won: { icon: "✓", cls: "st-won" },
  lost: { icon: "✕", cls: "st-lost" }, closed: { icon: "■", cls: "st-closed" }, unset: { icon: "!", cls: "st-unset" },
};

// ------------------------------------------------------------------ davrlar
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
/** n oy oldinga/orqaga; oy oxiri qisqasiga "qisiladi" (31-okt → 30-sen). */
const addMonths = (d: Date, n: number) => {
  const x = new Date(d.getFullYear(), d.getMonth() + n, 1);
  x.setDate(Math.min(d.getDate(), new Date(x.getFullYear(), x.getMonth() + 1, 0).getDate()));
  return x;
};
interface Range { from: string; to: string; gran: Gran; cmpFrom: string; cmpTo: string; cmpName: string }
/** Har tez tugma o'zining tabiiy taqqoslash davri bilan: bu oy (1–22) ↔ o'tgan oy (1–22), bu yil ↔ o'tgan yil shu kungacha. */
function preset(code: string): Range {
  const t = new Date(); const y = t.getFullYear(); const m = t.getMonth();
  switch (code) {
    case "today": return { from: iso(t), to: iso(t), gran: "day", cmpFrom: iso(addDays(t, -1)), cmpTo: iso(addDays(t, -1)), cmpName: "kecha" };
    case "week": {
      const s = addDays(t, -((t.getDay() + 6) % 7));
      return { from: iso(s), to: iso(t), gran: "day", cmpFrom: iso(addDays(s, -7)), cmpTo: iso(addDays(t, -7)), cmpName: "o'tgan hafta" };
    }
    case "month": { const s = new Date(y, m, 1);
      return { from: iso(s), to: iso(t), gran: "day", cmpFrom: iso(addMonths(s, -1)), cmpTo: iso(addMonths(t, -1)), cmpName: "o'tgan oy" }; }
    case "quarter": { const s = new Date(y, m - (m % 3), 1);
      return { from: iso(s), to: iso(t), gran: "month", cmpFrom: iso(addMonths(s, -3)), cmpTo: iso(addMonths(t, -3)), cmpName: "o'tgan chorak" }; }
    case "year": return { from: iso(new Date(y, 0, 1)), to: iso(t), gran: "month", cmpFrom: iso(new Date(y - 1, 0, 1)), cmpTo: iso(addMonths(t, -12)), cmpName: "o'tgan yil" };
    default: return { from: iso(new Date(y - 1, 0, 1)), to: iso(new Date(y - 1, 11, 31)), gran: "quarter",
                      cmpFrom: iso(new Date(y - 2, 0, 1)), cmpTo: iso(new Date(y - 2, 11, 31)), cmpName: `${y - 2}-yil` };
  }
}
const PRESETS = [["today", "Bugun"], ["week", "Bu hafta"], ["month", "Bu oy"], ["quarter", "Bu chorak"], ["year", "Bu yil"], ["lastyear", "O'tgan yil"]];
const GRANS: [Gran, string][] = [["day", "Kun"], ["month", "Oy"], ["quarter", "Chorak"], ["year", "Yil"]];

// ------------------------------------------------------------------ formatlar
const num = (v: Num | number | undefined) => (v === null || v === undefined || v === "" ? null : Number(v));
const usd = (v: Num | number | undefined, compact = false) => {
  const n = num(v);
  if (n === null) return "—";
  if (compact && Math.abs(n) >= 1000) {
    return "$" + (Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(Math.abs(n) >= 1e8 ? 0 : 1) + " mln" : (n / 1e3).toFixed(Math.abs(n) >= 1e5 ? 0 : 1) + " ming");
  }
  return "$" + Math.round(n).toLocaleString("ru-RU").replace(/,/g, " ");
};
const pct = (v: Num | number, digits = 1) => { const n = num(v); return n === null ? "—" : `${(n * 100).toFixed(digits).replace(/\.0$/, "")}%`; };
const int = (n: number) => n.toLocaleString("ru-RU");
const shortDate = (s: string) => { const [y, m, d] = s.split("-"); return `${d}.${m}.${y.slice(2)}`; };
/** KP hajmi oralig'i — ming USD da, qisqa: "<5", "5–10", "250+". */
const sizeLabel = (lo: number, hi: number | null) => (hi === null ? `${lo / 1000}+` : lo === 0 ? `<${hi / 1000}` : `${lo / 1000}–${hi / 1000}`);
const discLabel = (lo: string, hi: Num) => (hi === null ? `${pct(lo, 0)}+` : `${pct(lo, 0).replace("%", "")}–${pct(hi, 0)}`);

/** "Chiroyli" o'q: qadam 1, 2, 2.5, 5 × 10ⁿ (taxminan `count` bo'linma), yuqori chegara — qadamga karrali. */
function niceScale(max: number, count: number, integer = false) {
  const rough = Math.max(max, 1) / count;
  const p = 10 ** Math.floor(Math.log10(rough));
  let step = ([1, 2, 2.5, 5, 10].find((k) => k * p >= rough) ?? 10) * p;
  if (integer) step = Math.max(1, Math.ceil(step));
  const top = Math.max(step, Math.ceil(max / step) * step);
  return { top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step) };
}

// ------------------------------------------------------------------ KPI kartasi
/** O'zgarish: rang yolg'iz ma'no tashimaydi — strelka + belgi + matn. tone="neutral" — o'sish yaxshi ham, yomon ham emas. */
function Delta({ cur, prev, mode = "pct", tone = "up-good" }: { cur: number | null; prev: number | null; mode?: "pct" | "pp"; tone?: "up-good" | "neutral" }) {
  if (cur === null || prev === null) return <span className="delta flat">— taqqoslab bo'lmaydi</span>;
  if (mode === "pct" && prev === 0) return cur === 0 ? <span className="delta flat">● o'zgarishsiz</span> : <span className="delta flat">● avval yo'q edi</span>;
  const d = mode === "pct" ? (cur - prev) / Math.abs(prev) : cur - prev;
  const eps = mode === "pct" ? 0.0005 : 0.0005;
  if (Math.abs(d) < eps) return <span className="delta flat">● o'zgarishsiz</span>;
  const up = d > 0;
  const cls = tone === "neutral" ? "flat" : up ? "up" : "down";
  const txt = mode === "pct" ? `${(Math.abs(d) * 100).toFixed(Math.abs(d) >= 0.1 ? 0 : 1)}%` : `${(Math.abs(d) * 100).toFixed(1)} p.p.`;
  return <span className={"delta " + cls}>{up ? "▲" : "▼"} {up ? "+" : "−"}{txt}</span>;
}

function Kpi({ label, value, delta, sub, accent }: { label: string; value: string; delta?: React.ReactNode; sub?: React.ReactNode; accent?: string }) {
  return (
    <div className={"kpi" + (accent ? " " + accent : "")}>
      <span className="kpi-label">{label}</span>
      <b className="kpi-value">{value}</b>
      {delta}
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

// ------------------------------------------------------------------ Dinamika
/** Konteyner eni (px): grafik telefonda kichrayib ketmasin — SVG o'lchami haqiqiy enga teng, yozuvlar doim o'qiladigan. */
function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width) || fallback));
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, w] as const;
}

/** Joriy davr — ustunlar, taqqoslash davri — punktir chiziq. Ikkalasi bitta o'lchov (bitta o'q). */
function TrendChart({ data, metric, cmpName }: { data: Bucket[]; metric: "sum" | "count"; cmpName: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [box, width] = useWidth<HTMLDivElement>(900);
  const cur = (b: Bucket) => (metric === "sum" ? Number(b.kp_sum_usd) : b.kp_count);
  const prev = (b: Bucket) => (b.prev_label === null ? null : metric === "sum" ? Number(b.prev_kp_sum_usd) : (b.prev_kp_count ?? 0));
  const fmt = (v: number) => (metric === "sum" ? usd(v, true) : String(Math.round(v)));
  const W = Math.max(280, width), H = W < 560 ? 220 : 260, L = 52, R = 8, B = 28, T = 12;
  const { top: max, ticks } = niceScale(Math.max(...data.map(cur), ...data.map((b) => prev(b) ?? 0)), 4, metric === "count");
  const n = Math.max(1, data.length);
  const slot = (W - L - R) / n;
  const bw = Math.max(3, Math.min(30, slot * 0.62));
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const cx = (i: number) => L + i * slot + slot / 2;
  const every = Math.ceil(n / Math.max(1, Math.floor((W - L) / 56)));
  const pts = data.map((b, i) => [i, prev(b)] as const).filter(([, v]) => v !== null) as [number, number][];
  const line = pts.map(([i, v], k) => `${k ? "L" : "M"}${cx(i)},${y(v)}`).join(" ");
  const total = data.reduce((s, b) => s + cur(b), 0);
  const empty = total === 0 && pts.every(([, v]) => v === 0);
  const h = hover !== null ? data[hover] : null;
  return (
    <div className="chart-box" ref={box}>
      {empty ? <p className="muted chart-empty">Bu davrda va taqqoslash davrida KP tuzilmagan.</p> : <>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="KP dinamikasi" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" />
            <text x={L - 8} y={y(t) + 4} className="tick" textAnchor="end">{fmt(t)}</text>
          </g>
        ))}
        {data.map((b, i) => {
          const v = cur(b); const x = cx(i) - bw / 2; const top = y(v); const hh = H - B - top; const r = Math.min(4, bw / 2, hh);
          return (
            <g key={b.start}>
              {hover === i && <rect x={L + i * slot} y={T} width={slot} height={H - T - B} className="hover-band" />}
              {v > 0 && <path d={`M${x},${H - B} V${top + r} q0,-${r} ${r},-${r} h${bw - 2 * r} q${r},0 ${r},${r} V${H - B} Z`}
                              className="bar-cur" opacity={hover === null || hover === i ? 1 : 0.5} />}
              {i % every === 0 && <text x={cx(i)} y={H - 9} className="tick" textAnchor="middle">{b.label}</text>}
            </g>
          );
        })}
        {pts.length > 1 && <path d={line} className="line-prev" />}
        {pts.map(([i, v]) => (pts.length === 1 || hover === i) && <circle key={i} cx={cx(i)} cy={y(v)} r={4} className="dot-prev" />)}
        <line x1={L} x2={W - R} y1={H - B} y2={H - B} className="axis" />
        {data.map((b, i) => <rect key={b.start} x={L + i * slot} y={T} width={slot} height={H - T - B} fill="transparent" onMouseEnter={() => setHover(i)} />)}
      </svg>
      {h && hover !== null && (
        <div className="tooltip" style={{ left: `${Math.min(88, Math.max(12, (cx(hover) / W) * 100))}%` }}>
          <b>{h.label}</b>
          <span><i className="sw sw-cur" /> {fmt(cur(h))} {metric === "count" ? "ta KP" : ""}</span>
          {prev(h) !== null && <span className="muted"><i className="sw sw-prev" /> {h.prev_label}: {fmt(prev(h)!)}</span>}
          {prev(h) !== null && <Delta cur={cur(h)} prev={prev(h)} />}
        </div>
      )}
      <div className="legend">
        <span><i className="sw sw-cur" /> Tanlangan davr</span>
        <span><i className="sw sw-prev line" /> Taqqoslash: {cmpName}</span>
      </div>
      </>}
    </div>
  );
}

// ------------------------------------------------------------------ Kategoriyalar (halqa)
const CAT_SLOTS = 7; // 7 ta rang + "Boshqa" (kulrang) — 8-rang yaratilmaydi
function CategoryDonut({ data }: { data: Dash["categories"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const items = useMemo(() => {
    const valid = data.filter((c) => num(c.sum_usd) !== null && Number(c.sum_usd) > 0);
    const head = valid.slice(0, CAT_SLOTS).map((c, i) => ({ name: c.name, v: Number(c.sum_usd), kp: c.kp_count, cls: `cat-${i + 1}` }));
    const rest = valid.slice(CAT_SLOTS);
    if (rest.length) head.push({ name: `Boshqa (${rest.length} ta)`, v: rest.reduce((s, c) => s + Number(c.sum_usd), 0), kp: NaN, cls: "cat-other" });
    return head;
  }, [data]);
  const total = items.reduce((s, c) => s + c.v, 0);
  if (!total) return <p className="muted chart-empty">Bu davrda KP qatorlari yo'q.</p>;
  const R = 80, r = 54, C = 100;
  let a0 = -Math.PI / 2;
  const gap = items.length > 1 ? 0.012 : 0;
  const arcs = items.map((c) => {
    const span = (c.v / total) * Math.PI * 2;
    const s = a0 + gap, e = a0 + span - gap; a0 += span;
    if (e <= s) return { ...c, d: "" };
    const big = e - s > Math.PI ? 1 : 0;
    const p = (rad: number, ang: number) => `${C + rad * Math.cos(ang)},${C + rad * Math.sin(ang)}`;
    const full = span >= Math.PI * 2 - 1e-6;
    const d = full
      ? `M${C},${C - R} A${R},${R} 0 1 1 ${C - 0.01},${C - R} L${C - 0.01},${C - r} A${r},${r} 0 1 0 ${C},${C - r} Z`
      : `M${p(R, s)} A${R},${R} 0 ${big} 1 ${p(R, e)} L${p(r, e)} A${r},${r} 0 ${big} 0 ${p(r, s)} Z`;
    return { ...c, d };
  });
  const h = hover !== null ? items[hover] : null;
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 200 200" className="donut" role="img" aria-label="Mahsulot kategoriyalari ulushi" onMouseLeave={() => setHover(null)}>
        {arcs.map((c, i) => c.d && (
          <path key={c.name} d={c.d} className={c.cls} opacity={hover === null || hover === i ? 1 : 0.35} onMouseEnter={() => setHover(i)} />
        ))}
        <text x={C} y={C - 4} textAnchor="middle" className="donut-value">{h ? pct(h.v / total) : usd(total, true)}</text>
        <text x={C} y={C + 15} textAnchor="middle" className="donut-label">{h ? (h.name.length > 16 ? h.name.slice(0, 15) + "…" : h.name) : "jami"}</text>
      </svg>
      <table className="compact legend-table">
        <tbody>
          {items.map((c, i) => (
            <tr key={c.name} className={hover === i ? "hl" : ""} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <td><i className={"sw " + c.cls} /> {c.name}</td>
              <td className="num">{usd(c.v, true)}</td>
              <td className="num muted">{pct(c.v / total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ ustunli taqsimot (KP hajmi, chegirma)
function Histogram({ data, label, aria, cls, tip }: { data: { count: number }[]; label: (i: number) => string; aria: string; cls: string; tip: (i: number) => string }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 420, H = 190, L = 30, B = 34, T = 18;
  const { top: max, ticks } = niceScale(Math.max(4, ...data.map((d) => d.count)), 3, true);
  const slot = (W - L - 4) / data.length;
  const bw = Math.min(46, slot * 0.66);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}><line x1={L} x2={W - 4} y1={y(t)} y2={y(t)} className="grid" />
            <text x={L - 6} y={y(t) + 4} className="tick" textAnchor="end">{t}</text></g>
        ))}
        {data.map((d, i) => {
          const x = L + i * slot + (slot - bw) / 2; const top = y(d.count); const h = H - B - top; const r = Math.min(4, h);
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={L + i * slot} y={T} width={slot} height={H - T - B} fill="transparent" />
              {d.count > 0 && <path d={`M${x},${H - B} V${top + r} q0,-${r} ${r},-${r} h${bw - 2 * r} q${r},0 ${r},${r} V${H - B} Z`}
                                    className={cls} opacity={hover === null || hover === i ? 1 : 0.5} />}
              {d.count > 0 && <text x={x + bw / 2} y={top - 5} textAnchor="middle" className="bar-label">{d.count}</text>}
              <text x={x + bw / 2} y={H - 14} className="tick" textAnchor="middle">{label(i)}</text>
            </g>
          );
        })}
        <line x1={L} x2={W - 4} y1={H - B} y2={H - B} className="axis" />
      </svg>
      {hover !== null && (
        <div className="tooltip" style={{ left: `${Math.min(85, Math.max(15, ((L + hover * slot + slot / 2) / W) * 100))}%` }}>{tip(hover)}</div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ sahifa
export default function Dashboard() {
  const { can } = useAuth();
  const init = preset("month");
  const [p, setP] = useState("month");
  const [range, setRange] = useState<Range>(init);
  const [manager, setManager] = useState("");
  const [metric, setMetric] = useState<"sum" | "count">("sum");
  const [employees, setEmployees] = useState<{ id: number; full_name: string }[]>([]);
  const [d, setD] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const all = can("kp.view_all");

  useEffect(() => { if (all) api.get<{ id: number; full_name: string }[]>("/api/employees").then(setEmployees).catch(() => undefined); }, [all]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    const cmp = range.cmpFrom ? { compare_from: range.cmpFrom, compare_to: range.cmpTo } : {};
    api.get<Dash>("/api/dashboard" + qs({ date_from: range.from, date_to: range.to, granularity: range.gran, manager_id: manager || undefined, ...cmp }))
      .then((x) => { if (live) { setD(x); setError(""); } })
      .catch((e) => live && setError((e as Error).message))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [range, manager]);

  function choose(code: string) { setP(code); setRange(preset(code)); }
  // qo'lda tanlangan davr — taqqoslash: oldingi teng uzunlikdagi davr (backend hisoblaydi)
  const custom = (from: string, to: string) => { setP(""); setRange((r) => ({ ...r, from, to, cmpFrom: "", cmpTo: "", cmpName: "oldingi davr" })); };

  const s = d?.summary, v = d?.previous;
  const single = d ? d.period.scope === "own" || d.period.manager_id !== null : false;
  const cmpTitle = d ? `${shortDate(d.period.compare_from)} – ${shortDate(d.period.compare_to)}` : "";
  const projMax = d ? Math.max(1, ...d.projects.map((x) => Number(x.kp_sum_usd))) : 1;
  const mgrMax = d ? Math.max(1, ...d.managers.map((x) => Number(x.kp_sum_usd))) : 1;
  const priced = s ? s.kp_count - s.unpriced_count : 0;
  const pricedPrev = v ? v.kp_count - v.unpriced_count : 0;
  // bitta menejer ko'rinishida reyting o'rniga turadi, aks holda — top loyihalar yonida
  const sizesPanel = d && s && (
    <div className="panel chart">
      <div className="chart-head"><div><h2>KP hajmi taqsimoti</h2><p className="muted chart-sub">Nechta KP qaysi summa oralig'ida · ming USD, QQS bilan</p></div></div>
      {priced === 0 ? <p className="muted chart-empty">Bu davrda KP tuzilmagan.</p> : (
        <Histogram data={d.sizes} cls="bar-size" aria="KP hajmi taqsimoti" label={(i) => sizeLabel(d.sizes[i].lo, d.sizes[i].hi)}
                   tip={(i) => `${d.sizes[i].count} ta KP · jami ${usd(d.sizes[i].sum_usd, true)}`} />
      )}
      {priced > 1 && <p className="muted chart-foot">Odatiy KP (mediana) — <b className="ink">{usd(s.median_usd, true)}</b>, o'rtacha — {usd(s.avg_usd, true)}
        {Number(s.avg_usd) > 1.5 * Number(s.median_usd) ? " (o'rtachani bir nechta katta KP ko'taradi)" : ""}.</p>}
    </div>
  );

  return (
    <div className={"dash" + (loading && d ? " is-loading" : "")}>
      <div className="breadcrumb"><Link to="/">Bosh sahifa</Link> / <b>Dashboard</b></div>
      <div className="title-bar">
        <div>
          <h1>Dashboard</h1>
          {d && <p className="muted dash-period">{dateUz(d.period.from)} – {dateUz(d.period.to)} · taqqoslash: {range.cmpName} ({cmpTitle})</p>}
        </div>
        <span className="badge teal">{d?.period.scope === "own" ? "Mening ko'rsatkichlarim" : manager ? employees.find((e) => String(e.id) === manager)?.full_name : "Barcha menejerlar"}</span>
      </div>

      <div className="panel filterbar">
        <div className="seg" role="group" aria-label="Davr">{PRESETS.map(([c, t]) => <button key={c} type="button" className={p === c ? "on" : ""} onClick={() => choose(c)}>{t}</button>)}</div>
        <label>dan<input type="date" value={range.from} max={range.to} onChange={(e) => e.target.value && custom(e.target.value, range.to)} /></label>
        <label>gacha<input type="date" value={range.to} min={range.from} onChange={(e) => e.target.value && custom(range.from, e.target.value)} /></label>
        <label>Kesim
          <div className="seg" role="group" aria-label="Kesim">{GRANS.map(([g, t]) => <button key={g} type="button" className={range.gran === g ? "on" : ""} onClick={() => setRange((r) => ({ ...r, gran: g }))}>{t}</button>)}</div>
        </label>
        {all && (
          <label>Menejer
            <select value={manager} onChange={(e) => setManager(e.target.value)}>
              <option value="">— barchasi —</option>
              {employees.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
            </select>
          </label>
        )}
        {manager && <button type="button" className="link-btn" onClick={() => setManager("")}>✕ filtrni olib tashlash</button>}
      </div>
      {error && <div className="alert err">{error}</div>}

      {!d || !s || !v ? (
        <><div className="kpis">{[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton" style={{ height: 118 }} />)}</div><div className="skeleton block" /></>
      ) : (
        <>
          {/* ---------------- KPI */}
          <div className="kpis">
            <Kpi label="KP lar" value={int(s.kp_count)} delta={<Delta cur={s.kp_count} prev={v.kp_count} />}
                 sub={<>{s.revised_count ? `${s.revised_count} tasi qayta ko'rilgan` : "qayta ko'rilgan yo'q"} · avval {int(v.kp_count)}</>} />
            <Kpi label="Umumiy summa" value={usd(s.kp_sum_usd, true)} delta={<Delta cur={num(s.kp_sum_usd)} prev={num(v.kp_sum_usd)} />}
                 sub={s.unpriced_count ? <span className="warn-text">! {s.unpriced_count} ta KP narxi to'liq emas — summaga kirmagan</span> : <>{usd(s.kp_sum_usd)} · QQS bilan</>} />
            <Kpi label="O'rtacha KP" value={usd(s.avg_usd, true)} delta={<Delta cur={priced ? num(s.avg_usd) : null} prev={pricedPrev ? num(v.avg_usd) : null} />}
                 sub={<>narxi ma'lum {int(priced)} ta KP bo'yicha</>} />
            <Kpi label="Chegirmali KP" accent="disc" value={priced ? pct(s.discounted_count / priced, 0) : "—"}
                 delta={<Delta mode="pp" tone="neutral" cur={priced ? s.discounted_count / priced : null} prev={pricedPrev ? v.discounted_count / pricedPrev : null} />}
                 sub={s.discounted_count ? <>{s.discounted_count} ta KP · {usd(s.discount_usd, true)} berildi</> : "chegirma berilmagan"} />
            <Kpi label="Loyihalar" value={int(s.projects)} delta={<Delta cur={s.projects} prev={v.projects} />}
                 sub={<>{s.new_projects} tasi yangi (birinchi KP shu davrda)</>} />
            {!single && (
              <Kpi label="Faol menejerlar" value={int(s.managers)} delta={<Delta cur={s.managers} prev={v.managers} />}
                   sub={s.managers ? <>har biriga o'rtacha {(s.kp_count / s.managers).toFixed(1).replace(/\.0$/, "")} ta KP</> : "—"} />
            )}
          </div>

          {/* ---------------- Dinamika */}
          <div className="panel chart">
            <div className="chart-head">
              <div><h2>Dinamika</h2><p className="muted chart-sub">{metric === "sum" ? "KP summasi, USD (QQS bilan)" : "Tuzilgan KP lar soni"} — {GRANS.find(([g]) => g === range.gran)?.[1].toLowerCase()} kesimida</p></div>
              <div className="seg" role="group" aria-label="O'lchov">
                <button type="button" className={metric === "sum" ? "on" : ""} onClick={() => setMetric("sum")}>Summa</button>
                <button type="button" className={metric === "count" ? "on" : ""} onClick={() => setMetric("count")}>Soni</button>
              </div>
            </div>
            <TrendChart data={d.series} metric={metric} cmpName={range.cmpName} />
          </div>

          {/* ---------------- Tarkib: kategoriyalar + menejerlar / KP hajmi */}
          <div className="grid2">
            <div className="panel chart">
              <div className="chart-head"><div><h2>Mahsulot kategoriyalari</h2><p className="muted chart-sub">Summa qaysi mahsulotlardan tashkil topgan (chegirmadan keyin)</p></div></div>
              <CategoryDonut data={d.categories} />
            </div>
            {!single ? (
              <div className="panel">
                <div className="chart-head"><div><h2>Menejerlar reytingi</h2><p className="muted chart-sub">Summa bo'yicha · bosilsa — shu menejer filtri</p></div></div>
                {d.managers.length === 0 ? <p className="muted chart-empty">Bu davrda KP tuzilmagan.</p> : (
                  <div className="rank">
                    {d.managers.map((m, i) => (
                      <button type="button" key={m.manager_id} className="rank-row" onClick={() => setManager(String(m.manager_id))}
                              title={`${m.manager_name}: ${m.kp_count} ta KP, ${usd(m.kp_sum_usd)}`}>
                        <span className="rank-no">{i + 1}</span>
                        <span className="rank-name"><b>{m.manager_name}</b>
                          <span className="muted">{m.kp_count} KP · o'rt. {usd(m.avg_usd, true)} · {m.projects} loyiha{m.discounted_count ? ` · chegirma ${pct(m.discount_rate)}` : ""}</span></span>
                        <span className="rank-bar"><span style={{ width: `${(Number(m.kp_sum_usd) / mgrMax) * 100}%` }} /></span>
                        <span className="rank-val"><b>{usd(m.kp_sum_usd, true)}</b><span className="muted">{pct(m.share, 0)}</span></span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : sizesPanel}
          </div>

          {/* ---------------- Top loyihalar + KP hajmi */}
          <div className="grid2">
            <div className="panel table-wrap">
              <div className="chart-head"><div><h2>Top loyihalar</h2><p className="muted chart-sub">Davrdagi KP summasi bo'yicha eng katta 10 ta</p></div></div>
              {d.projects.length === 0 ? <p className="muted chart-empty">Bu davrda KP tuzilmagan.</p> : (
                <table className="compact top-projects">
                  <tbody>
                    {d.projects.map((x, i) => (
                      <tr key={x.project_id}>
                        <td className="rank-no-cell">{i + 1}</td>
                        <td>
                          <div className="prj-name"><b>{x.project_name}</b>{x.is_new && <span className="badge ok">yangi</span>}</div>
                          <div className="inline-bar"><span style={{ width: `${(Number(x.kp_sum_usd) / projMax) * 100}%` }} /></div>
                          <div className="muted prj-meta">{x.kp_count} KP · {x.managers.join(", ")} · oxirgisi <Link to={`/kp/${x.last_kp}`}>№ {x.last_kp}</Link></div>
                        </td>
                        <td className="num"><b>{usd(x.kp_sum_usd, true)}</b></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {!single && sizesPanel}
          </div>

          {/* ---------------- Chegirma tahlili */}
          <div className="panel">
            <div className="chart-head"><div><h2>Chegirma tahlili</h2>
              <p className="muted chart-sub">{s.discounted_count
                ? <>{s.discounted_count} ta KP da {usd(s.discount_usd)} chegirma — chegirmagacha summaning {pct(s.discount_rate)} qismi</>
                : "Bu davrda chegirma berilmagan."}</p></div></div>
            {s.discounted_count > 0 && (
              <div className="grid2 inner">
                <div className="chart">
                  <h3 className="sub-h">Chegirma chuqurligi (KP soni)</h3>
                  <Histogram data={d.discounts.buckets} cls="bar-disc" aria="Chegirma foizi bo'yicha KP lar" label={(i) => discLabel(d.discounts.buckets[i].lo, d.discounts.buckets[i].hi)}
                             tip={(i) => `${d.discounts.buckets[i].count} ta KP · ${usd(d.discounts.buckets[i].discount_usd, true)} chegirma`} />
                </div>
                <div className="table-wrap">
                  <h3 className="sub-h">Eng katta chegirmalar</h3>
                  <table className="compact">
                    <tbody>
                      {d.discounts.top.map((x) => (
                        <tr key={x.kp_number}>
                          <td><Link to={`/kp/${x.kp_number}`}>№ {x.kp_number}</Link><div className="muted">{x.project_name} · {x.manager_name}</div></td>
                          <td className="num"><span className="badge disc">−{pct(x.rate)}</span></td>
                          <td className="num"><b>{usd(x.discount_usd, true)}</b><div className="muted">KP {usd(x.total_usd, true)}</div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {DEAL_TRACKING && (
            <div className="grid2">
              <div className="panel">
                <h2>Holatlar bo'yicha</h2>
                <table className="compact"><tbody>
                  {[...d.by_status, { code: "unset", name: "Belgilanmagan", count: d.kpi.unset_count, sum_usd: d.kpi.unset_sum_usd }].map((x) => (
                    <tr key={x.code}><td><span className={"chip-st " + DEAL_LOOK[x.code].cls}>{DEAL_LOOK[x.code].icon}</span> {x.name}</td>
                      <td className="num"><b>{x.count}</b></td><td className="num">{usd(x.sum_usd)}</td></tr>
                  ))}
                </tbody></table>
              </div>
              <div className="panel table-wrap">
                <h2>Oxirgi sotuvlar</h2>
                {d.wins.length === 0 ? <p className="muted">Bu davrda sotuv yo'q.</p> : (
                  <table className="compact"><tbody>
                    {d.wins.map((w) => (
                      <tr key={w.kp_number}><td><Link to={`/kp/${w.kp_number}`}>№ {w.kp_number}</Link><div className="muted">{w.project_name}</div></td>
                        <td className="muted">{w.manager_name}<div>{dateUz(w.sold_on)}</div></td><td className="num"><b>{usd(w.sold_usd)}</b></td></tr>
                    ))}
                  </tbody></table>
                )}
              </div>
            </div>
          )}
          <p className="muted dash-note">Summalar USD da, QQS bilan, chegirmadan keyin (so'mdagi KP — shu KP dagi tasdiqlangan kurs bilan). KP davri — KP birinchi tuzilgan sana;
            summa — oxirgi revisiya bo'yicha. Narxi to'liq bo'lmagan KP lar sonda bor, summada yo'q.</p>
        </>
      )}
    </div>
  );
}
