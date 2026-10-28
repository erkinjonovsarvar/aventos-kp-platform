import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

const MIN = 10;

export default function Join() {
  const { token } = useParams();
  const [state, setState] = useState<"checking" | "valid" | "invalid" | "sent">("checking");
  const [form, setForm] = useState({ full_name: "", phone: "", email: "", position: "", password: "", password2: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/api/join/${token}`).then(() => setState("valid")).catch(() => setState("invalid"));
  }, [token]);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (form.password !== form.password2) return setError("Parollar mos kelmadi");
    setBusy(true);
    setError("");
    try {
      await api.post(`/api/join/${token}`, {
        full_name: form.full_name.trim(), phone: form.phone.trim(), email: form.email || null,
        position: form.position || null, password: form.password,
      });
      setState("sent");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <div className="login-card" style={{ maxWidth: 440 }}>
        <h1>AVENTOS KP — kirish so'rovi</h1>
        {state === "checking" && <p className="muted">Havola tekshirilmoqda…</p>}
        {state === "invalid" && <div className="alert err">Havola yaroqsiz, ishlatilgan yoki muddati tugagan. Administratorga murojaat qiling.</div>}
        {state === "sent" && <div className="alert ok">So'rovingiz yuborildi. Administrator tasdiqlagach, login va parolingiz bilan kirasiz.</div>}
        {state === "valid" && (
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p className="muted" style={{ margin: 0 }}>Ma'lumotlaringizni kiriting. Parolni o'zingiz o'ylab toping — uni hech kim ko'rmaydi.</p>
            {error && <div className="alert err">{error}</div>}
            <label>F.I.Sh. (kirillcha)<input value={form.full_name} onChange={set("full_name")} required minLength={3} /></label>
            <label>Telefon<input value={form.phone} onChange={set("phone")} required minLength={7} placeholder="+998 __ ___ __ __" /></label>
            <label>Email (ixtiyoriy)<input type="email" value={form.email} onChange={set("email")} /></label>
            <label>Lavozim (ixtiyoriy)<input value={form.position} onChange={set("position")} /></label>
            <label>Parol (kamida {MIN} belgi)<input type="password" value={form.password} onChange={set("password")} required minLength={MIN} autoComplete="new-password" /></label>
            <label>Parolni takrorlang<input type="password" value={form.password2} onChange={set("password2")} required minLength={MIN} autoComplete="new-password" /></label>
            <button type="submit" disabled={busy}>{busy ? "Yuborilmoqda…" : "So'rov yuborish"}</button>
          </form>
        )}
      </div>
    </div>
  );
}
