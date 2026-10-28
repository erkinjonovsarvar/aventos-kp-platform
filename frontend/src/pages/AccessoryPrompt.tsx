import { useEffect, useState } from "react";
import { api } from "../api";

interface Need { model: string; need: string; have: string }
interface Needs { panels: (Need & { after_line_no: number })[]; pult: Need }

function readSkip(key: string) {
  try { return localStorage.getItem(key) === "1"; } catch { return false; }
}
function writeSkip(key: string) {
  try { localStorage.setItem(key, "1"); } catch { /* brauzer xotirasi yopiq — faqat shu safar yashiriladi */ }
}

/** Qo'lda kasseta/kanalniy blok qo'shilganda panel va pult yetishmasa — "Qo'shasizmi?" (Ha / Yo'q, kerak emas). */
export default function AccessoryPrompt({ kp, revisionNo, annexNo, version, onAdded, onError }:
  { kp: number; revisionNo: number; annexNo: number; version: string; onAdded: (added: string[]) => void; onError: (m: string) => void }) {
  const [needs, setNeeds] = useState<Needs | null>(null);
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<Needs>(`/api/quotations/${kp}/annexes/${annexNo}/accessories`).then(setNeeds).catch(() => setNeeds(null));
  }, [kp, annexNo, version]);
  if (!needs) return null;

  const missingPanels = needs.panels.filter((p) => Number(p.need) > Number(p.have));
  const pultMissing = Number(needs.pult.need) > Number(needs.pult.have);
  // "Yo'q" — shu holat uchun eslab qolinadi; yangi blok qo'shilsa (soni o'zgarsa) yana so'raladi
  const key = (kind: string, sig: string) => `aventos.acc.${kp}.${revisionNo}.${annexNo}.${kind}.${sig}`;
  const panelKey = key("panel", missingPanels.map((p) => `${p.model}:${p.need}`).join(","));
  const pultKey = key("pult", needs.pult.need);
  const showPanel = missingPanels.length > 0 && !hidden[panelKey] && !readSkip(panelKey);
  const showPult = pultMissing && !hidden[pultKey] && !readSkip(pultKey);
  if (!showPanel && !showPult) return null;

  async function yes(panels: boolean, pult: boolean) {
    setBusy(true);
    try {
      const r = await api.post<{ added: string[] }>(`/api/quotations/${kp}/annexes/${annexNo}/accessories`, { panels, pult });
      onAdded(r.added);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function no(k: string) {
    writeSkip(k);
    setHidden((h) => ({ ...h, [k]: true }));
  }
  return (
    <>
      {showPanel && (
        <div className="prompt">
          <span style={{ fontSize: 20 }}>⚠️</span>
          <span className="q">
            <b>Kasseta bloklari uchun panel qo'shilmagan.</b>{" "}
            Kerak: {missingPanels.map((p) => `${p.model} × ${Number(p.need) - Number(p.have)}`).join(", ")}.
            <br /><span className="muted">Panel qo'shasizmi? Har panel o'z kasseta guruhidan keyingi qatorga, soniga qarab qo'shiladi.</span>
          </span>
          <button className="accent" disabled={busy} onClick={() => void yes(true, false)}>Ha, qo'shish</button>
          <button className="secondary" disabled={busy} onClick={() => no(panelKey)}>Yo'q, kerak emas</button>
        </div>
      )}
      {showPult && (
        <div className="prompt">
          <span style={{ fontSize: 20 }}>🎛️</span>
          <span className="q">
            <b>Pult qo'shilmagan.</b> Kasseta va kanalniy bloklar: {Number(needs.pult.need)} ta, pult: {Number(needs.pult.have)} ta.
            <br /><span className="muted">Pult qo'shasizmi? {needs.pult.model} × {Number(needs.pult.need) - Number(needs.pult.have)} ilova oxiriga qo'shiladi.</span>
          </span>
          <button className="accent" disabled={busy} onClick={() => void yes(false, true)}>Ha, qo'shish</button>
          <button className="secondary" disabled={busy} onClick={() => no(pultKey)}>Yo'q, kerak emas</button>
        </div>
      )}
    </>
  );
}
