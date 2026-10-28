import { useCallback, useEffect, useState } from "react";
import { api, dateUz } from "../api";
import { toast } from "../toast";

interface Inv { id: number; note: string | null; created_at: string; expires_at: string; used_at: string | null; state: string }
const STATE: Record<string, [string, string]> = {
  active: ["faol", "ok"], used: ["ishlatilgan", ""], expired: ["muddati o'tgan", ""], revoked: ["bekor qilingan", "err"],
};

export default function Invitations() {
  const [items, setItems] = useState<Inv[]>([]);
  const [note, setNote] = useState("");
  const [hours, setHours] = useState(72);
  const [link, setLink] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => { api.get<Inv[]>("/api/admin/invitations").then(setItems).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);

  async function create() {
    try {
      const r = await api.post<{ link: string }>("/api/admin/invitations", { note: note || null, valid_hours: hours });
      setLink(r.link);
      setCopied(false);
      setNote("");
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <h1>Taklif havolalari</h1>
      <div className="panel">
        <p className="muted" style={{ marginTop: 0 }}>
          Havola faqat AVENTOS xodimiga yuboriladi. U <b>bir marta</b> ishlatiladi va belgilangan vaqtdan keyin yaroqsiz bo'ladi.
          Xodim havola orqali so'rov yuboradi — siz "So'rovlar" bo'limida tasdiqlaysiz, muddat va imkoniyatlarni belgilaysiz.
        </p>
        <div className="row">
          <label>Kimga (izoh)<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="masalan: Иванов Иван" size={30} /></label>
          <label>Amal qilish (soat)<input type="number" min={1} max={720} value={hours} onChange={(e) => setHours(Number(e.target.value))} /></label>
          <button onClick={() => void create()}>Havola yaratish</button>
        </div>
        {error && <div className="alert err" style={{ marginTop: 12 }}>{error}</div>}
        {link && (
          <div className="alert ok" style={{ marginTop: 12 }}>
            <b>Havola tayyor — faqat hozir ko'rsatiladi, nusxalab oling:</b>
            <div className="row" style={{ marginTop: 6 }}>
              <span className="mono">{link}</span>
              <button className="secondary" onClick={() => void navigator.clipboard.writeText(link).then(() => setCopied(true))}>
                {copied ? "Nusxalandi ✓" : "Nusxalash"}
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>ID</th><th>Kimga</th><th>Yaratilgan</th><th>Amal qiladi</th><th>Holat</th><th></th></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td>{i.id}</td><td>{i.note ?? "—"}</td><td>{dateUz(i.created_at)}</td>
                <td>{new Date(i.expires_at).toLocaleString("ru-RU")}</td>
                <td><span className={`badge ${STATE[i.state]?.[1] ?? ""}`}>{STATE[i.state]?.[0] ?? i.state}</span></td>
                <td>
                  {i.state === "active" && (
                    <button className="danger small" onClick={() => {
                      if (!window.confirm(`Havola #${i.id}${i.note ? ` (${i.note})` : ""} bekor qilinsinmi? U endi ishlamaydi.`)) return;
                      api.post(`/api/admin/invitations/${i.id}/revoke`).then(() => { toast("Havola bekor qilindi"); load(); })
                        .catch((e) => setError(e.message));
                    }}>Bekor qilish</button>
                  )}
                </td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={6} className="muted">Hali havola yaratilmagan</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
