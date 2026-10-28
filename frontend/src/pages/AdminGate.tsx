import { useState, type FormEvent, type ReactNode } from "react";
import { api, type User } from "../api";
import { useAuth } from "../auth";

/** Admin paneli darvozasi: faqat admin o'zi biladigan maxfiy so'z (foydalanuvchi talabi 2026-10-17).
 *  Birinchi marta — so'z o'rnatiladi; keyin har sessiyada (15 daqiqa harakatsizlikdan keyin ham) so'raladi. */
export default function AdminGate({ children }: { children: ReactNode }) {
  const { user, refresh } = useAuth();
  const [word, setWord] = useState("");
  const [word2, setWord2] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user?.admin_unlocked) return <>{children}</>;
  const setup = !user?.admin_word_set;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (setup && word !== word2) { setError("Ikki so'z bir xil emas"); return; }
    setBusy(true);
    try {
      if (setup) await api.post<User>("/api/auth/admin-word/set", { password, word });
      else await api.post<User>("/api/auth/admin-word/verify", { word });
      setWord(""); setWord2(""); setPassword("");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
      await refresh().catch(() => undefined);       // ko'p xatodan keyin sessiya yopilgan bo'lishi mumkin
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form className="login-card" onSubmit={submit}>
        <div className="gate-ico" aria-hidden>🔐</div>
        <h1>{setup ? "Admin paneli uchun maxfiy so'z" : "Maxfiy so'zni kiriting"}</h1>
        <p className="muted" style={{ margin: 0, textAlign: "center" }}>
          {setup
            ? "Bu so'zni faqat siz bilasiz — hech kimga (dasturchiga ham) aytmang. Parolingizdan farqli bo'lsin, kamida 8 belgi."
            : "Admin paneli qo'shimcha himoyalangan. 5 marta xato kiritilsa — barcha qurilmalardan chiqarilasiz."}
        </p>
        {error && <div className="alert err">{error}</div>}
        {setup && (
          <label>Hozirgi parolingiz
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
        )}
        <label>{setup ? "Yangi maxfiy so'z" : "Maxfiy so'z"}
          <input type="password" value={word} onChange={(e) => setWord(e.target.value)} autoComplete="off" minLength={setup ? 8 : undefined}
                 autoFocus required />
        </label>
        {setup && (
          <label>Maxfiy so'zni takrorlang
            <input type="password" value={word2} onChange={(e) => setWord2(e.target.value)} autoComplete="off" required />
          </label>
        )}
        <button type="submit" disabled={busy}>{busy ? "Tekshirilmoqda…" : setup ? "O'rnatish" : "Ochish"}</button>
      </form>
    </div>
  );
}
