import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, dateUz } from "../api";
import { useAuth } from "../auth";
import { DEAL_TRACKING } from "../features";

interface Item { kp_number: number; project_name: string; created_on: string }
interface Rem { count: number; items: Item[] }

function useReminders(): Rem | null {
  const { user, can } = useAuth();
  const location = useLocation();
  const [r, setR] = useState<Rem | null>(null);
  const allowed = DEAL_TRACKING && !!user && can("deal.update");
  useEffect(() => {
    if (!allowed) { setR(null); return; }
    api.get<Rem>("/api/deal/reminders").then(setR).catch(() => setR(null));
  }, [allowed, location.pathname]);
  return r;
}

/** Menyudagi qizil sanoq: savdo holati belgilanmagan o'z KP lari soni. */
export function useReminderCount(): number {
  return useReminders()?.count ?? 0;
}

/** Muloyim eslatma: tasdiqlangan/yuborilgan, lekin savdo holati belgilanmagan KP lar. */
export default function Reminder() {
  const r = useReminders();
  const [hidden, setHidden] = useState(false);
  if (!r || r.count === 0 || hidden) return null;
  return (
    <div className="reminder">
      <span style={{ fontSize: 18 }}>🔔</span>
      <span style={{ flex: 1, minWidth: 240 }}>
        <b>{r.count} ta KP ingizga savdo holati belgilanmagan.</b> Iltimos, vaqt topib belgilab qo'ying —
        Jarayonda, Sotildi, Yutqazildi yoki Loyiha yopildi.{" "}
        {r.items.slice(0, 5).map((i, n) => (
          <span key={i.kp_number}>{n ? ", " : ""}<Link to={`/kp/${i.kp_number}`} title={`${i.project_name} · ${dateUz(i.created_on)}`}>№ {i.kp_number}</Link></span>
        ))}
        {r.count > 5 && <span> va yana {r.count - 5} ta</span>}
      </span>
      <button className="secondary small" onClick={() => setHidden(true)}>Keyinroq</button>
    </div>
  );
}
