import { useEffect, useState } from "react";
import { api, money, qs } from "../api";

interface TypeRow { type: string; models: string; capacity_unit: string | null }
export interface CatalogItem {
  model: string; type: string | null; series: string | null; capacity: string | null; capacity_unit: string | null;
  price_excl_vat: string | null; price_incl_vat: string | null; diff: string | null;
}

// Eng ko'p ishlatiladigan turlar — bir bosishda tanlash uchun
const QUICK = ["VRF наружный блок", "VRF ВБ (мини четырехкасетный)", "VRF ВБ (четырехкасетный)", "VRF ВБ (однокасетный)",
  "VRF ВБ (настенный)", "VRF ВБ (высоконапорный канальный)", "Панель", "Проводной пульт", "Чиллер"];

/** Katalogdan model tanlash: tur (kategoriya) + kW (eng yaqin quvvat birinchi) + matn. */
export default function CatalogPicker({ onPick, onClose }: { onPick: (item: CatalogItem) => void; onClose: () => void }) {
  const [types, setTypes] = useState<TypeRow[]>([]);
  const [type, setType] = useState("VRF наружный блок");
  const [kw, setKw] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.get<TypeRow[]>("/api/price-list/types").then(setTypes).catch(() => undefined); }, []);
  useEffect(() => {
    const k = kw.trim().replace(",", ".");
    if (k && !/^\d+(\.\d+)?$/.test(k)) return;
    setBusy(true);
    const t = setTimeout(() => {
      api.get<CatalogItem[]>("/api/price-list/find" + qs({ type: type || undefined, kw: k || undefined, q: q.trim() || undefined }))
        .then(setItems).catch(() => setItems([])).finally(() => setBusy(false));
    }, 200);
    return () => clearTimeout(t);
  }, [type, kw, q]);

  const quick = QUICK.filter((t) => types.some((x) => x.type === t));
  const unit = types.find((x) => x.type === type)?.capacity_unit ?? "kw";
  return (
    <div className="picker">
      <div className="picker-head">
        <b>Katalogdan model tanlash</b>
        <button className="secondary small" onClick={onClose}>Yopish ✕</button>
      </div>
      <div className="chips">
        {quick.map((t) => (
          <button key={t} className={"chip" + (t === type ? " on" : "")} onClick={() => setType(t)}>{t}</button>
        ))}
      </div>
      <div className="row" style={{ marginBottom: 10 }}>
        <label>Turi (kategoriya)
          <select value={type} onChange={(e) => setType(e.target.value)} style={{ width: 340, maxWidth: "100%" }}>
            <option value="">— hammasi —</option>
            {types.map((t) => <option key={t.type} value={t.type}>{t.type} ({t.models})</option>)}
          </select>
        </label>
        <label>Quvvat, {unit}
          <input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="masalan 56" size={8} autoFocus />
        </label>
        <label>Model / seriya
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="masalan AVWT, Neo, HKF5" size={18} />
        </label>
        <span className="muted" style={{ paddingBottom: 9 }}>{busy ? "Qidirilmoqda…" : `${items.length} ta model`}</span>
      </div>
      <div className="picker-results">
        <table>
          <thead>
            <tr><th>Model</th><th>Turi</th><th>Seriya</th><th className="num">Quvvat</th>
              <th className="num">Narx QQSsiz</th><th className="num">QQS bilan</th><th></th></tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.model} className="clickable" onClick={() => onPick(it)}>
                <td><b>{it.model}</b></td>
                <td>{it.type}</td>
                <td className="muted">{it.series}</td>
                <td className={"num" + (it.diff !== null && Number(it.diff) === 0 ? " diff0" : "")}>
                  {it.capacity !== null ? `${Number(it.capacity)} ${it.capacity_unit ?? ""}` : "—"}
                </td>
                <td className="num">{money(it.price_excl_vat)}</td>
                <td className="num">{money(it.price_incl_vat)}</td>
                <td><button className="accent small" onClick={(e) => { e.stopPropagation(); onPick(it); }}>Tanlash</button></td>
              </tr>
            ))}
            {!busy && items.length === 0 && <tr><td colSpan={7} className="muted">Mos model topilmadi</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
