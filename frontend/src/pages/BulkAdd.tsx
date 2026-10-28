import { useState } from "react";
import { api, money } from "../api";
import { toast } from "../toast";

/** Excel'dan nusxalangan ro'yxat (Model / Soni / Narx) bilan ommaviy qo'shish (foydalanuvchi talabi 2026-10-19).
 *  Ctrl+V -> tekshiruv jadvali (topildi / o'xshash / topilmadi / xato) -> "Hammasini qo'shish". Narx taxmin qilinmaydi:
 *  katalogda yo'q model uchun narxni foydalanuvchi yozadi, yozilmasa — narxsiz (TEKSHIRISH KERAK) qo'shiladi. */

interface Match { model: string; type: string | null; capacity: string | null; capacity_unit: string | null; price_incl_vat: string | null }
interface Item {
  row: number; merged_rows: number[]; model_raw: string; quantity: string | null; price: string | null;
  status: "found" | "corrected" | "similar" | "not_found" | "error"; model: string | null; match: Match | null; suggestions: Match[]; error: string | null;
}
interface Preview { items: Item[]; counts: Record<string, number>; header: boolean; price_vat: "incl" | "excl" | null }
interface Row extends Item { use: string; qty: string; manualPrice: string; desc: string; drop: boolean; confirmed: boolean }

const MANUAL = "__manual__";
const STATUS: Record<Item["status"], [string, string]> = {
  found: ["✅", "Topildi"], corrected: ["🟢", "To'g'rilandi"], similar: ["🟡", "O'xshashi bor"], not_found: ["⚪", "Katalogda yo'q"], error: ["🔴", "Xato"],
};

/** Mavjud qatorga yig'ilgan model: bekor qilishda soni old_quantity ga qaytariladi. */
export type MergedLine = { line_id: number; line_no: number; old_quantity: string };

export default function BulkAdd({ kp, annexNo, onDone, onError, onClose }: {
  kp: number; annexNo: number; onDone: (lineIds: number[], warnings: string[], merged: MergedLine[]) => void; onError: (m: string) => void;
  onClose?: () => void;   // menyudan ochilganda — darhol ochiq, "Yopish" menyuga qaytaradi
}) {
  const [open, setOpen] = useState(!!onClose);
  const [raw, setRaw] = useState("");
  const [merge, setMerge] = useState(true);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (i: number, patch: Partial<Row>) => setRows((rs) => rs && rs.map((r, n) => (n === i ? { ...r, ...patch } : r)));

  async function check(text = raw) {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const p = await api.post<Preview>(`/api/quotations/${kp}/annexes/${annexNo}/bulk/preview`, { text, merge });
      setRows(p.items.map((it) => ({
        ...it, use: it.status === "not_found" ? MANUAL : it.model ?? MANUAL, qty: it.quantity ?? "",
        // Excel narxi "с НДС" bo'lsa — qo'lda narx maydoniga QQSsiz (÷1,12) qo'yiladi
        manualPrice: it.price ? (p.price_vat === "incl" ? (Number(it.price) / 1.12).toFixed(2) : it.price) : "",
        desc: it.model_raw, drop: false, confirmed: it.status !== "similar",
      })));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const active = (rows ?? []).filter((r) => !r.drop);
  const qtyOk = (r: Row) => Number(r.qty.replace(",", ".")) > 0;
  const blockers = active.filter((r) => !qtyOk(r) || (r.status === "similar" && !r.confirmed && r.use !== MANUAL));
  const noPrice = active.filter((r) => r.use === MANUAL && !r.manualPrice.trim()).length;

  async function addAll() {
    setBusy(true);
    try {
      const items = active.map((r) => r.use === MANUAL
        ? { model: r.model_raw, quantity: r.qty.replace(",", "."), from_catalog: false,
            price_excl_vat: r.manualPrice.trim() ? r.manualPrice.replace(/\s/g, "").replace(",", ".") : null, description: r.desc || r.model_raw }
        : { model: r.use, quantity: r.qty.replace(",", ".") });
      const res = await api.post<{ added: number; line_ids: number[]; merged: MergedLine[]; warnings: string[] }>(
        `/api/quotations/${kp}/annexes/${annexNo}/bulk`, { items });
      // Ilovada bor model yangi qator ochmaydi — birinchi qatoriga yig'iladi (qaror 2026-10-21)
      const merged = res.merged ?? [];          // eski server "merged" qaytarmaydi
      toast(`${res.added} ta qator qo'shildi` + (merged.length ? `, ${merged.length} ta model mavjud qatoriga yig'ildi` : ""));
      setRows(null); setRaw(""); setOpen(false);
      onDone(res.line_ids, res.warnings, merged);
      onClose?.();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return <button className="secondary" style={{ marginTop: 10 }} onClick={() => setOpen(true)}>📋 Ro'yxatdan qo'shish (Excel'dan)</button>;
  }
  return (
    <div className="picker bulk">
      <div className="picker-head">
        <b>📋 Excel'dan ro'yxat bilan qo'shish</b>
        <button className="secondary small" onClick={() => { setOpen(false); setRows(null); setRaw(""); onClose?.(); }}>Yopish</button>
      </div>
      {!rows && (
        <>
          <p className="muted" style={{ marginTop: 0 }}>
            Excel'da <b>Model</b> va <b>Soni</b> ustunlarini (xohlasangiz <b>Narx</b> ham) belgilab nusxalang (Ctrl+C) va shu yerga joylang (Ctrl+V).
            Sarlavha bo'lsa ham, bo'lmasa ham bo'ladi.
          </p>
          <textarea className="bulk-input" rows={8} value={raw} placeholder={"AVS-12HJDTD\t15\nAVS-15HJDTD\t8\nAVBC-38HJDBA\t3"}
                    onChange={(e) => setRaw(e.target.value)}
                    onPaste={(e) => { const t = e.clipboardData.getData("text"); if (t) { e.preventDefault(); setRaw(t); void check(t); } }} />
          <div className="row" style={{ marginTop: 8 }}>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={merge} onChange={(e) => setMerge(e.target.checked)} /> bir xil modellarni birlashtirish
            </label>
            <button disabled={busy || !raw.trim()} onClick={() => void check()}>{busy ? "Tekshirilmoqda…" : "Tekshirish"}</button>
          </div>
        </>
      )}
      {rows && (
        <>
          <div className="row bulk-summary">
            {(["found", "corrected", "similar", "not_found", "error"] as const).map((s) => {
              const n = rows.filter((r) => r.status === s && !r.drop).length;
              return n ? <span key={s} className={"bulk-chip " + s}>{STATUS[s][0]} {STATUS[s][1]}: <b>{n}</b></span> : null;
            })}
            <button className="secondary small" onClick={() => setRows(null)}>← Ro'yxatni o'zgartirish</button>
          </div>
          <div className="picker-results">
            <table className="compact">
              <thead><tr><th></th><th>Excel'dagi</th><th>Qo'shiladigan model</th><th>Tur / quvvat</th><th className="num">Soni</th><th className="num">Narx (QQS bilan)</th><th></th></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className={"bulk-row " + r.status + (r.drop ? " dropped" : "")}>
                    <td title={STATUS[r.status][1] + (r.error ? ": " + r.error : "")}>{STATUS[r.status][0]}</td>
                    <td><b>{r.model_raw}</b>{r.merged_rows.length > 1 && <div className="muted">{r.merged_rows.length} qator birlashdi</div>}
                      {r.error && <div className="err-text" style={{ fontSize: 12 }}>{r.error}</div>}</td>
                    <td>
                      {r.status === "found" && r.use}
                      {(r.status === "similar" || r.status === "corrected" || r.status === "not_found" || (r.status === "error" && r.suggestions.length > 0)) && (
                        <select value={r.use} onChange={(e) => set(i, { use: e.target.value, confirmed: true })}>
                          {r.suggestions.map((s) => <option key={s.model} value={s.model}>{s.model}</option>)}
                          <option value={MANUAL}>Katalogda yo'q — qo'lda narx</option>
                        </select>
                      )}
                      {r.status === "error" && r.suggestions.length === 0 && r.use !== MANUAL && r.use}
                      {r.status === "similar" && !r.confirmed && r.use !== MANUAL && (
                        <button className="small" style={{ marginLeft: 6 }} onClick={() => set(i, { confirmed: true })}>✓ To'g'ri</button>
                      )}
                      {r.use === MANUAL && (
                        <input className="bulk-desc" value={r.desc} onChange={(e) => set(i, { desc: e.target.value })} placeholder="Наименование" />
                      )}
                    </td>
                    <td className="muted">{r.use !== MANUAL && r.match ? `${r.match.type ?? ""}${r.match.capacity ? ` · ${r.match.capacity} ${r.match.capacity_unit ?? ""}` : ""}` : "—"}</td>
                    <td className="num"><input value={r.qty} onChange={(e) => set(i, { qty: e.target.value })} size={5} inputMode="decimal"
                                               className={qtyOk(r) ? "" : "invalid"} /></td>
                    <td className="num">
                      {r.use === MANUAL
                        ? <input value={r.manualPrice} onChange={(e) => set(i, { manualPrice: e.target.value })} size={8} inputMode="decimal"
                                 placeholder="QQSsiz, USD" title="Katalogda yo'q: QQSsiz narx (USD). Bo'sh qolsa — narxsiz qo'shiladi (TEKSHIRISH KERAK)" />
                        : (r.suggestions.find((s) => s.model === r.use) ?? r.match)?.price_incl_vat
                          ? money((r.suggestions.find((s) => s.model === r.use) ?? r.match)!.price_incl_vat!) : "—"}
                    </td>
                    <td><button className="secondary small" title={r.drop ? "Qaytarish" : "Bu qatorni qo'shmaslik"}
                                onClick={() => set(i, { drop: !r.drop })}>{r.drop ? "↺" : "✕"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {blockers.length > 0 && <div className="alert warn" style={{ marginTop: 10 }}>
            {blockers.length} ta qator tayyor emas: sonini to'g'rilang, 🟡 o'xshash modelni tasdiqlang (✓) yoki qatorni olib tashlang (✕).</div>}
          {noPrice > 0 && <div className="muted" style={{ marginTop: 6 }}>{noPrice} ta katalogda yo'q qatorga narx yozilmagan — narxsiz qo'shiladi (KP tasdiqlanmaydi, keyin narxini kiritasiz).</div>}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="accent" disabled={busy || active.length === 0 || blockers.length > 0} onClick={() => void addAll()}>
              {busy ? "Qo'shilmoqda…" : `Hammasini qo'shish (${active.length} ta)`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
