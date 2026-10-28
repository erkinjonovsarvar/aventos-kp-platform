import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, dateUz, qs } from "../api";
import { toast } from "../toast";

interface Issue {
  id: number;
  table_name: string;
  record_id: string;
  issue_code: string;
  details: string | null;
  found_at: string;
  resolved_at: string | null;
  resolution: string | null;
  resolved_by_name: string | null;
}

/** Texnik kodlar — odam tilida (UX audit 2026-10-17, 7-band). */
const ISSUE_UZ: Record<string, string> = {
  UNKNOWN_CATEGORY: "Kategoriya ro'yxatda yo'q",
  PERFORMANCE_TEXT: "Quvvat raqam emas",
  PRICE_VAT_RULE: "QQS bilan narx 12% qoidasiga mos emas",
  MISSING_PRICE: "Narx topilmadi",
  QTY_ASSUMED: "Soni yozilmagan (1 deb olindi)",
  MISSING_UNIT: "O'lchov birligi yo'q",
  UNKNOWN_UNIT: "O'lchov birligi ro'yxatda yo'q",
  SENT_FILE_MISSING: "Yuborilgan Excel fayl topilmadi",
  SENT_FILE_DIFFERS: "Yuborilgan fayl bazadan farq qiladi",
  MULTIPLE_ANNEX_NAMES: "Ilovada bir nechta nom",
  RATE_UNKNOWN: "Valyuta kursi aniqlanmadi",
  MIXED_CURRENCY: "Bitta KP da ikki valyuta",
  NEGATIVE_QTY: "Soni noto'g'ri (manfiy/bo'sh)",
  SENT_WITHOUT_VAT: "QQSsiz yuborilgan",
  SUSPICIOUS_RATE: "Kurs shubhali",
};

const kpOf = (i: Issue) => i.details?.match(/KP (\d{7})/)?.[1] ?? null;

/** Tafsilotni o'qishga oson qilish: "KP 1001695, DB!11:" -> "Excel DB, 11-qator:"; None -> bo'sh. */
function humanDetails(d: string | null): string {
  if (!d) return "";
  return d
    .replace(/^KP \d{7},?\s*/, "")
    .replace(/\bDB!(\d+)/g, "Excel DB, $1-qator")
    .replace(/DATABASE PRICE!(\d+)/g, "narx ro'yxati, $1-qator")
    .replace(/\bNone\b/g, "bo'sh")
    .replace(/'#N\/A'/g, "#N/A (Excel xatosi)");
}

export default function Issues() {
  const [openOnly, setOpenOnly] = useState(true);
  const [code, setCode] = useState("");
  const [kpSearch, setKpSearch] = useState("");
  const [items, setItems] = useState<Issue[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    api.get<Issue[]>("/api/data-issues" + qs({ open_only: openOnly })).then(setItems).catch((e) => setError(e.message));
  }, [openOnly]);
  useEffect(load, [load]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (items ?? []).forEach((i) => { c[i.issue_code] = (c[i.issue_code] ?? 0) + 1; });
    return c;
  }, [items]);

  // KP bo'yicha guruhlash (KP siz yozuvlar — "Narx ro'yxati va boshqalar")
  const groups = useMemo(() => {
    const g = new Map<string, Issue[]>();
    (items ?? [])
      .filter((i) => !code || i.issue_code === code)
      .filter((i) => !kpSearch.trim() || (kpOf(i) ?? "").startsWith(kpSearch.trim()))
      .forEach((i) => { const k = kpOf(i) ?? "—"; g.set(k, [...(g.get(k) ?? []), i]); });
    return [...g.entries()].sort((a, b) => (a[0] === "—" ? 1 : b[0] === "—" ? -1 : b[0].localeCompare(a[0])));
  }, [items, code, kpSearch]);

  async function resolveMany(key: string, list: Issue[]) {
    const open = list.filter((i) => !i.resolved_at);
    if (!open.length || !window.confirm(`${open.length} ta yozuv "Shundayligicha qoladi" deb yopilsinmi? (ma'lumot o'zgarmaydi)`)) return;
    setBusy(key);
    try {
      for (const i of open) await api.post(`/api/data-issues/${i.id}/resolve`, { resolution: "Shundayligicha qoladi" });
      toast(`${open.length} ta yozuv yopildi`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      load();
    }
  }

  const shown = groups.reduce((n, [, l]) => n + l.length, 0);
  return (
    <>
      <h1>Tekshirish kerak</h1>
      <p className="muted" style={{ marginTop: -6 }}>
        Eski Excel bazadan ko'chirishda topilgan noaniqliklar. Ko'pchiligi eski KP larga tegishli — ma'lumot o'zgarmaydi,
        faqat ko'rib chiqib yopiladi. Tuzatish kerak bo'lsa (narx, kategoriya) — Claude orqali.
      </p>
      <div className="panel filterbar">
        <label>Turi
          <select value={code} onChange={(e) => setCode(e.target.value)}>
            <option value="">— hammasi ({items?.length ?? 0}) —</option>
            {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([c, n]) => <option key={c} value={c}>{ISSUE_UZ[c] ?? c} ({n})</option>)}
          </select>
        </label>
        <label>KP raqami<input value={kpSearch} onChange={(e) => setKpSearch(e.target.value.replace(/\D/g, ""))} placeholder="masalan 1001695" size={14} inputMode="numeric" /></label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> faqat ochiqlar
        </label>
        <span className="muted" style={{ marginLeft: "auto" }}>{shown} ta yozuv · {groups.length} ta KP</span>
      </div>
      {error && <div className="alert err">{error}</div>}
      {!items && <><div className="skeleton row" /><div className="skeleton row" /><div className="skeleton row" /></>}
      {items && groups.length === 0 && <div className="panel muted">Yozuv yo'q 🎉</div>}
      {groups.map(([kp, list]) => {
        const open = expanded.has(kp);
        const openCount = list.filter((i) => !i.resolved_at).length;
        const kinds = [...new Set(list.map((i) => ISSUE_UZ[i.issue_code] ?? i.issue_code))];
        return (
          <div className="panel issue-group" key={kp}>
            <div className="issue-head">
              <button className="secondary small" aria-expanded={open}
                      onClick={() => setExpanded((s) => { const n = new Set(s); if (n.has(kp)) n.delete(kp); else n.add(kp); return n; })}>
                {open ? "▾" : "▸"}
              </button>
              <b>{kp === "—" ? "Narx ro'yxati va boshqalar" : <Link to={`/kp/${kp}`}>KP {kp} →</Link>}</b>
              <span className="badge warn">{list.length} ta</span>
              <span className="muted issue-kinds">{kinds.join(" · ")}</span>
              {openCount > 0 && (
                <button className="secondary small" disabled={busy !== null} onClick={() => void resolveMany(kp, list)}>
                  {busy === kp ? "Yopilmoqda…" : `Hammasini yopish (${openCount})`}
                </button>
              )}
            </div>
            {open && (
              <table className="compact">
                <tbody>
                  {list.map((i) => (
                    <tr key={i.id}>
                      <td style={{ width: 230 }}><b>{ISSUE_UZ[i.issue_code] ?? i.issue_code}</b></td>
                      <td className="desc">{humanDetails(i.details)}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {i.resolved_at
                          ? <span className="badge ok" title={`${i.resolved_by_name ?? ""}, ${dateUz(i.resolved_at)}: ${i.resolution ?? ""}`}>yopilgan</span>
                          : <button className="secondary small" disabled={busy !== null} onClick={() => void resolveMany(String(i.id), [i])}>Yopish</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </>
  );
}
