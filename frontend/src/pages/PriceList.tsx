import { useEffect, useState } from "react";
import { api, dateUz, money } from "../api";
import { useAuth } from "../auth";
import { toast } from "../toast";

/** Narx ro'yxati (foydalanuvchi talabi 2026-10-22): joriy katalog, versiyalar tarixi va platformaning o'zida yangilash —
 *  Excel'dan ro'yxat (Ctrl+V) yoki bitta mahsulot formasi -> tekshiruv -> yangi versiya. Eski versiya o'zgarmaydi. */

interface CatalogRow {
  model: string; brand: string; series: string; description: string | null; capacity: string | null; capacity_unit: string | null;
  price_excl_vat: string; price_incl_vat: string; valid_from: string;
}
interface Version { id: number; name: string; valid_from: string; approved_at: string; approved_by_name: string | null; items: number }
interface Raw { row: number; model: string | null; description: string | null; capacity: string | null; unit: string | null;
  brand: string | null; series: string | null; price_excl_vat: string | null; price_incl_vat: string | null }
interface Checked extends Raw {
  status: "new" | "changed" | "same" | "error"; errors: string[]; warnings: string[];
  changes: { field: string; old: string | null; new: string | null }[];
  value: { model: string; description: string | null; capacity: string | null; capacity_unit: string | null;
    price_excl_vat: string | null; price_incl_vat: string | null; brand: string; series: string } | null;
}
interface CheckResult { items: Checked[]; counts: Record<string, number>; layout?: string; header?: boolean }

const STATUS: Record<Checked["status"], [string, string]> = {
  new: ["🆕", "Yangi"], changed: ["✏️", "O'zgargan"], same: ["＝", "O'zgarmagan"], error: ["🔴", "Xato"],
};
const FIELD_UZ: Record<string, string> = {
  description: "tavsif", capacity: "quvvat", capacity_unit: "birlik", price_excl_vat: "QQSsiz", price_incl_vat: "QQS bilan",
};
const UNITS = ["", "kw", "m3/h", "kg/h", "btu", "л"];
const EMPTY: Raw = { row: 1, model: "", description: "", capacity: "", unit: "", brand: "", series: "", price_excl_vat: "", price_incl_vat: "" };
const raw = (c: Checked): Raw => ({ row: c.row, model: c.model, description: c.description, capacity: c.capacity, unit: c.unit,
  brand: c.brand, series: c.series, price_excl_vat: c.price_excl_vat, price_incl_vat: c.price_incl_vat });
const fmt = (f: string, v: string | null) => (v === null || v === "" ? "—" : f.startsWith("price") ? money(v) : v);

function Editor({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [mode, setMode] = useState<"list" | "one">("list");
  const [text, setText] = useState("");
  const [one, setOne] = useState<Raw>(EMPTY);
  const [res, setRes] = useState<CheckResult | null>(null);
  const [drop, setDrop] = useState<Set<number>>(new Set());
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run<T>(f: () => Promise<T>): Promise<T | undefined> {
    setBusy(true); setErr("");
    try { return await f(); } catch (e) { setErr((e as Error).message); return undefined; } finally { setBusy(false); }
  }
  const parse = (t = text) => t.trim() && run(async () => {
    setRes(await api.post<CheckResult>("/api/price-list/changes/parse", { text: t })); setDrop(new Set());
  });
  const checkOne = () => run(async () => {
    setRes(await api.post<CheckResult>("/api/price-list/changes/check", { items: [one] })); setDrop(new Set());
  });

  const items = res?.items ?? [];
  const active = items.filter((i) => !drop.has(i.row));
  const todo = active.filter((i) => i.status === "new" || i.status === "changed");
  const errors = active.filter((i) => i.status === "error");
  const toggle = (row: number) => setDrop((d) => { const n = new Set(d); if (n.has(row)) n.delete(row); else n.add(row); return n; });

  const apply = () => run(async () => {
    const r = await api.post<{ name: string; added: number; changed: number }>("/api/price-list/changes/apply", {
      items: todo.map(raw), name: name.trim() || null,
      source: mode === "list" ? "Platforma: Excel'dan ro'yxat" : "Platforma: bitta mahsulot formasi",
    });
    toast(`Yangi versiya: ${r.added} ta yangi, ${r.changed} ta o'zgargan mahsulot`);
    onDone();
  });

  return (
    <div className="picker bulk">
      <div className="picker-head">
        <b>Mahsulot qo'shish / narxni yangilash</b>
        <button className="secondary small" onClick={onClose}>Yopish</button>
      </div>
      {!res && (
        <>
          <div className="chips">
            <button className={"chip" + (mode === "list" ? " on" : "")} onClick={() => setMode("list")}>📋 Excel'dan ro'yxat</button>
            <button className={"chip" + (mode === "one" ? " on" : "")} onClick={() => setMode("one")}>✏️ Bitta mahsulot</button>
          </div>
          {mode === "list" ? (
            <>
              <p className="muted" style={{ marginTop: 0 }}>
                Excel'da qatorlarni belgilab nusxalang (Ctrl+C) va shu yerga joylang (Ctrl+V). Ikki usul bor:
                <br />• <b>sarlavha qatori bilan</b>: kamida <b>Model</b> va <b>Narx</b> (с НДС / без НДС) ustunlari; qo'shimcha: Наименование,
                Quvvat, Birlik (kw / m3/h), Brend, Seriya;
                <br />• <b>sarlavhasiz</b>: Original DB'ning <i>DB 16.05.2026</i> varag'idan (A–K) yoki Price database jadvalidan (A–H)
                to'liq qatorlar.
                <br />Faqat QQS bilan narx bo'lsa, QQSsiz narx ÷1,12 bilan hisoblanadi. Bor modelning bo'sh katagi o'zgarmaydi.
              </p>
              <textarea className="bulk-input" rows={8} value={text}
                        placeholder={"Model\tНаименование\tQuvvat\tBirlik\tЦена с НДС\nHRV 1000\tРекуператор\t1000\tm3/h\t1456"}
                        onChange={(e) => setText(e.target.value)}
                        onPaste={(e) => { const t = e.clipboardData.getData("text"); if (t) { e.preventDefault(); setText(t); void parse(t); } }} />
              <div className="row" style={{ marginTop: 8 }}>
                <button disabled={busy || !text.trim()} onClick={() => void parse()}>{busy ? "Tekshirilmoqda…" : "Tekshirish"}</button>
              </div>
            </>
          ) : (
            <>
              <div className="form-grid">
                {([["model", "Model *"], ["description", "Наименование (tavsif)"], ["capacity", "Quvvat"],
                   ["brand", "Brend"], ["series", "Seriya"], ["price_incl_vat", "Narx QQS bilan, USD"],
                   ["price_excl_vat", "yoki Narx QQSsiz, USD"]] as [keyof Raw, string][]).map(([k, label]) => (
                  <label key={k}>{label}
                    <input value={String(one[k] ?? "")} inputMode={k.startsWith("price") || k === "capacity" ? "decimal" : undefined}
                           onChange={(e) => setOne({ ...one, [k]: e.target.value })} />
                  </label>
                ))}
                <label>Birlik
                  <select value={one.unit ?? ""} onChange={(e) => setOne({ ...one, unit: e.target.value })}>
                    {UNITS.map((u) => <option key={u} value={u}>{u || "—"}</option>)}
                  </select>
                </label>
              </div>
              <p className="muted">Bitta narx yetarli: QQS bilan narx berilsa QQSsiz ÷1,12, QQSsiz berilsa QQS bilan = ROUNDUP(×1,12).</p>
              <div className="row"><button disabled={busy || !one.model?.trim()} onClick={() => void checkOne()}>{busy ? "Tekshirilmoqda…" : "Tekshirish"}</button></div>
            </>
          )}
        </>
      )}
      {res && (
        <>
          <div className="row bulk-summary">
            {(["new", "changed", "same", "error"] as const).map((s) => {
              const n = active.filter((i) => i.status === s).length;
              return n ? <span key={s} className={"bulk-chip " + s}>{STATUS[s][0]} {STATUS[s][1]}: <b>{n}</b></span> : null;
            })}
            {res.layout && <span className="muted">Ustunlar: {res.layout}</span>}
            <button className="secondary small" onClick={() => setRes(null)}>← O'zgartirish</button>
          </div>
          <div className="picker-results">
            <table className="compact">
              <thead><tr><th></th><th>Qator</th><th>Model</th><th>Tavsif / quvvat</th><th className="num">QQSsiz</th>
                <th className="num">QQS bilan</th><th>Izoh</th><th></th></tr></thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.row} className={"bulk-row " + i.status + (drop.has(i.row) ? " dropped" : "")}>
                    <td title={STATUS[i.status][1]}>{STATUS[i.status][0]}</td>
                    <td className="muted">{i.row}</td>
                    <td><b>{i.value?.model ?? i.model ?? "—"}</b>
                      {i.status === "new" && i.value && <div className="muted">{i.value.brand} · {i.value.series}</div>}</td>
                    <td>{i.value?.description ?? i.description ?? "—"}
                      {i.value?.capacity && <div className="muted">{i.value.capacity} {i.value.capacity_unit ?? ""}</div>}</td>
                    <td className="num">{money(i.value?.price_excl_vat ?? null)}</td>
                    <td className="num"><b>{money(i.value?.price_incl_vat ?? null)}</b></td>
                    <td style={{ fontSize: 12.5 }}>
                      {i.errors.map((e) => <div key={e} style={{ color: "var(--err)", fontWeight: 600 }}>{e}</div>)}
                      {i.changes.map((c) => <div key={c.field}>{FIELD_UZ[c.field] ?? c.field}: {fmt(c.field, c.old)} → <b>{fmt(c.field, c.new)}</b></div>)}
                      {i.warnings.map((w) => <div key={w} className="muted">{w}</div>)}
                    </td>
                    <td>{i.status !== "same" && (
                      <button className="secondary small" title={drop.has(i.row) ? "Qaytarish" : "Bu qatorni qo'shmaslik"}
                              onClick={() => toggle(i.row)}>{drop.has(i.row) ? "↺" : "✕"}</button>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {errors.length > 0 && <div className="alert warn" style={{ marginTop: 10 }}>
            {errors.length} ta qatorda xato: Excel'da tuzatib qayta joylang yoki qatorni olib tashlang (✕).{" "}
            <button className="secondary small" onClick={() => setDrop(new Set([...drop, ...errors.map((e) => e.row)]))}>Xatolarni olib tashlash</button>
          </div>}
          <div className="row" style={{ marginTop: 10, alignItems: "flex-end" }}>
            <label style={{ flex: 1, minWidth: 220 }}>Versiya nomi (ixtiyoriy)
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="masalan: AVENTOS HRV rekuperatorlar" />
            </label>
            <button className="accent" disabled={busy || todo.length === 0 || errors.length > 0} onClick={() => void apply()}>
              {busy ? "Saqlanmoqda…" : `Tasdiqlash: yangi versiya (${todo.length} ta)`}
            </button>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>
            Tasdiqlanganda narx ro'yxatining yangi versiyasi yaratiladi. Eski versiya va yuborilgan KP lar o'zgarmaydi; yangi KP lar yangi narxni oladi.
          </p>
        </>
      )}
      {err && <div className="alert err" style={{ marginTop: 10 }}>{err}</div>}
    </div>
  );
}

export default function PriceList() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [data, setData] = useState<{ items: CatalogRow[]; total: number } | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [edit, setEdit] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => {
      api.get<{ items: CatalogRow[]; total: number }>(`/api/price-list/current?limit=300&q=${encodeURIComponent(q.trim())}`)
        .then(setData).catch((e) => toast((e as Error).message, "err"));
    }, 250);
    return () => window.clearTimeout(t);
  }, [q, reload]);
  useEffect(() => { api.get<Version[]>("/api/price-list/versions").then(setVersions).catch(() => undefined); }, [reload]);

  const cur = versions[0];
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ marginBottom: 4 }}>Narx ro'yxati</h1>
          {cur && <div className="muted">Joriy versiya: <b>{cur.name}</b> · {dateUz(cur.valid_from)} · {data?.total ?? "…"} ta model</div>}
        </div>
        {can("price.manage") && !edit && <button onClick={() => setEdit(true)}>➕ Mahsulot qo'shish / narxni yangilash</button>}
      </div>
      {edit && <Editor onClose={() => setEdit(false)} onDone={() => { setEdit(false); setReload((n) => n + 1); }} />}

      <div className="row" style={{ marginTop: 14 }}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Qidirish: model, tavsif, brend, seriya…" style={{ flex: 1 }} />
        <button className="secondary" onClick={() => setShowVersions(!showVersions)}>🕘 Versiyalar ({versions.length})</button>
      </div>
      {showVersions && (
        <div className="panel table-wrap" style={{ marginTop: 10 }}>
          <table className="compact">
            <thead><tr><th>Versiya</th><th>Sana</th><th>Kim tasdiqlagan</th><th className="num">Modellar</th></tr></thead>
            <tbody>{versions.map((v, n) => (
              <tr key={v.id}><td>{v.name}{n === 0 && <span className="bulk-chip new" style={{ marginLeft: 6 }}>joriy</span>}</td>
                <td>{dateUz(v.valid_from)}</td><td>{v.approved_by_name ?? "—"}</td><td className="num">{v.items}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <div className="panel table-wrap" style={{ marginTop: 10 }}>
        <table className="compact">
          <thead><tr><th>Model</th><th>Brend / seriya</th><th>Tavsif</th><th>Quvvat</th><th className="num">QQSsiz, USD</th><th className="num">QQS bilan, USD</th></tr></thead>
          <tbody>
            {data?.items.map((r) => (
              <tr key={r.model}>
                <td><b>{r.model}</b></td>
                <td className="muted">{r.brand}{r.series && r.series !== "(seriyasiz)" ? ` · ${r.series}` : ""}</td>
                <td>{r.description ?? "—"}</td>
                <td style={{ whiteSpace: "nowrap" }}>{r.capacity ? `${Number(r.capacity)} ${r.capacity_unit ?? ""}` : "—"}</td>
                <td className="num" title={r.price_excl_vat}>{money(r.price_excl_vat)}</td>
                <td className="num"><b>{money(r.price_incl_vat)}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 && <p className="muted">Hech narsa topilmadi.</p>}
        {data && data.items.length >= 300 && <p className="muted">Birinchi 300 ta ko'rsatildi — aniqroq qidiring.</p>}
      </div>
    </>
  );
}
