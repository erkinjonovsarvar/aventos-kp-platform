import { useState } from "react";
import { api, ApiError, dateUz, money, qs } from "../api";
import { toast } from "../toast";

/** Mavjud KP ga AHU faylini qo'shish (2026-10-20): yangi ilova sifatida yoki tanlangan ilova oxiriga.
 *  Avval VRF/katalog bilan ochilgan KP ga ham AHU qo'shish mumkin; 2-, 3-ilova alohida fayllardan. */

interface OfferItem { id: number; source_row: number; block_code: string; unit_label: string | null; parent_label: string | null; model: string | null; quantity: string; unit_price: string }
interface Offer { id: number; project_name_raw: string | null; offer_date: string | null; file_name: string; items: OfferItem[]; warnings?: string[]; hidden_rows?: number }
interface Orphan { row: number; block: string; label: string | null; model: string | null }
interface OrphanFix { file: File; message: string; orphans: Orphan[]; ahu: { row: number; label: string | null; model: string | null }[]; choice: Record<number, string> }

const BLOCK_UZ: Record<string, string> = { AHU: "AHU", AUTOMATION: "Automation", VRF: "VRF", KIT: "AHU kit", VALVE: "3-way valve" };

export default function AhuUpload({ kp, annexNo, projectName, onDone, onClose, onError }: {
  kp: number; annexNo?: number; projectName: string;
  onDone: (warnings: string[]) => void; onClose: () => void; onError: (m: string) => void;
}) {
  const [offer, setOffer] = useState<Offer | null>(null);
  const [orphanFix, setOrphanFix] = useState<OrphanFix | null>(null);
  const [name, setName] = useState("AHU");
  const [busy, setBusy] = useState(false);

  async function onFile(file: File | undefined, fixes?: Record<number, string>) {
    if (!file) return;
    setBusy(true);
    try {
      setOffer(await api.upload<Offer>("/api/ahu-offers" + qs({ fixes: fixes ? JSON.stringify(fixes) : undefined }), file));
      setOrphanFix(null);
    } catch (e) {
      const d = e instanceof ApiError ? (e.data as Partial<OrphanFix> | undefined) : undefined;
      if (d && Array.isArray(d.orphans) && Array.isArray(d.ahu)) {
        setOrphanFix({ file, message: (e as Error).message, orphans: d.orphans, ahu: d.ahu, choice: {} });
        setOffer(null);
      } else onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    if (!offer) return;
    setBusy(true);
    try {
      const r = await api.post<{ annex_no: number; added: number; warnings: string[] }>(`/api/quotations/${kp}/ahu`,
        { ahu_offer_id: offer.id, annex_no: annexNo ?? null, name: name.trim() || "AHU" });
      toast(`${r.added} ta qator ${r.annex_no}-ilovaga qo'shildi`);
      onDone(r.warnings);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const count = (b: string) => offer?.items.filter((i) => i.block_code === b).length ?? 0;
  return (
    <div className="picker">
      <div className="picker-head">
        <b>🌀 AHU faylidan {annexNo ? `— ${annexNo}-ilovaga qo'shish` : "— yangi ilova"}</b>
        <button className="secondary small" onClick={onClose}>Yopish</button>
      </div>
      <label>AHU fayli (.xlsx)
        <input type="file" accept=".xlsx" disabled={busy} onChange={(e) => void onFile(e.target.files?.[0])} />
      </label>
      {busy && !offer && <p className="muted">O'qilmoqda…</p>}
      {orphanFix && (
        <div className="prompt" style={{ display: "block", marginTop: 10 }}>
          <b>{orphanFix.orphans.length} ta qatorning AHU yorlig'i (A ustuni) hech bir AHU ga mos kelmadi.</b>
          <p className="muted" style={{ margin: "4px 0 10px" }}>Har biri qaysi AHU ga tegishli ekanini tanlang — fayl o'zgarmaydi.</p>
          <table className="compact">
            <thead><tr><th>Qator</th><th>Blok</th><th>Model</th><th>Yorliq</th><th>Qaysi AHU ga?</th></tr></thead>
            <tbody>
              {orphanFix.orphans.map((o) => (
                <tr key={o.row}>
                  <td>{o.row}</td><td>{BLOCK_UZ[o.block] ?? o.block}</td><td>{o.model}</td><td>{o.label ?? "bo'sh"}</td>
                  <td>
                    <select value={orphanFix.choice[o.row] ?? ""}
                            onChange={(e) => setOrphanFix({ ...orphanFix, choice: { ...orphanFix.choice, [o.row]: e.target.value } })}>
                      <option value="">— tanlang —</option>
                      {orphanFix.ahu.map((a) => <option key={a.row} value={a.row}>{a.label} — {a.model}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="accent" style={{ marginTop: 8 }} disabled={busy || orphanFix.orphans.some((o) => !orphanFix.choice[o.row])}
                  onClick={() => void onFile(orphanFix.file, orphanFix.choice)}>Bog'lab davom etish</button>
        </div>
      )}
      {offer && (
        <div style={{ marginTop: 10 }}>
          <p style={{ margin: "0 0 6px" }}>
            <b>{offer.file_name}</b> — fayldagi loyiha: <b>{offer.project_name_raw ?? "—"}</b>, sana: {dateUz(offer.offer_date)}
            {offer.hidden_rows ? <span className="muted"> · yashirin qatorlar (kiritilmaydi): {offer.hidden_rows}</span> : null}
          </p>
          {offer.project_name_raw && projectName && offer.project_name_raw.trim().toLowerCase() !== projectName.trim().toLowerCase() && (
            <div className="muted" style={{ marginBottom: 6 }}>KP loyihasi: <b>{projectName}</b> (fayldagi nom boshqacha — to'g'ri faylligini tekshiring)</div>
          )}
          {offer.warnings?.map((w) => <div className="alert warn" key={w}>{w}</div>)}
          <div className="row bulk-summary">
            {["AHU", "AUTOMATION", "VRF", "KIT", "VALVE"].map((b) => count(b) ? <span key={b} className="bulk-chip found">{BLOCK_UZ[b]}: <b>{count(b)}</b></span> : null)}
          </div>
          <div className="picker-results">
            <table className="compact">
              <thead><tr><th>Blok</th><th>AHU</th><th>Model</th><th className="num">Soni</th><th className="num">Narx (fayl)</th></tr></thead>
              <tbody>
                {offer.items.map((i) => (
                  <tr key={i.id}>
                    <td>{BLOCK_UZ[i.block_code] ?? i.block_code}</td><td>{i.unit_label ?? i.parent_label ?? "—"}</td>
                    <td>{i.model ?? ""}</td><td className="num">{i.quantity}</td><td className="num">{money(i.unit_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            {!annexNo && <label>Ilova nomi<input value={name} onChange={(e) => setName(e.target.value)} size={24} /></label>}
            <button className="accent" disabled={busy} onClick={() => void add()}>
              {busy ? "Qo'shilmoqda…" : annexNo ? `✓ ${annexNo}-ilovaga qo'shish` : "✓ Yangi ilova qilib qo'shish"}
            </button>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>AHU narxi = AHU + automation; marjani qo'shilgandan keyin har qatorga kiritasiz. VRF va kit — narx ro'yxatidan.</p>
        </div>
      )}
    </div>
  );
}
