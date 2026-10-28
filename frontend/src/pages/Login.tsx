import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Logo, ThemeToggle } from "../theme";

export default function Login() {
  const { user, login, verifyMfa, telegramError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [tgName, setTgName] = useState<string | null>(null);
  const [info, setInfo] = useState("");

  // faqat o'z sahifalarimizga qaytish (ochiq yo'naltirish "//boshqa.sayt" yoki "/\..." bo'lmasin — xavfsizlik auditi)
  const raw = (location.state as { from?: string } | null)?.from ?? "/";
  const from = /^\/(?![/\\])/.test(raw) ? raw : "/";
  if (user) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mfaToken) {
        await verifyMfa(mfaToken, code.trim());
        navigate(from, { replace: true });
      } else {
        const t = await login(name.trim(), password);
        if (t) { setMfaToken(t.token); setTgName(t.telegram); setPassword(""); } else navigate(from, { replace: true });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <section className="auth-hero">
        <img src="/logo.png" alt="AVENTOS air design" style={{ height: 38, filter: "brightness(0) invert(1)", alignSelf: "flex-start" }} />
        <div>
          <h2>Tijoriy takliflar — tez, aniq va bir joyda</h2>
          <p>Shamollatish va konditsionerlash loyihalari uchun KP tayyorlash tizimi.</p>
          {/* Kirishdan oldin biznes ma'lumoti (KP soni, katalog hajmi) ko'rsatilmaydi — faqat ish jarayoni */}
          <ol className="flow">
            <li><span className="flow-ico" aria-hidden>⬆</span><div><b>Manba</b><span>Podbor fayli yoki katalogdan model</span></div></li>
            <li><span className="flow-ico" aria-hidden>⚙</span><div><b>Hisob</b><span>Narx, marja va soliq qoidalar asosida</span></div></li>
            <li><span className="flow-ico" aria-hidden>✓</span><div><b>Taklif</b><span>Tasdiqlangan KP mijozga tayyor</span></div></li>
          </ol>
        </div>
        <span style={{ fontSize: 12, color: "#a9c4c8" }}>AVENTOS air design · KP Management System</span>
        <img className="fan" src="/icon.png" alt="" aria-hidden />
      </section>
      <div className="auth-form">
        <ThemeToggle />
      <form className="login-card" onSubmit={submit}>
        <Logo className="logo" />
        <h1>{mfaToken ? "Tasdiqlash kodi" : "Tizimga kirish"}</h1>
        {error && <div className="alert err">{error}</div>}
        {!error && telegramError && <div className="alert err">Telegram orqali kirib bo'lmadi: {telegramError}</div>}
        {mfaToken ? (
          <>
            <p className="muted" style={{ margin: 0, textAlign: "center" }}>
              Telegram'ingizga{tgName ? <b> ({tgName})</b> : null} 6 xonali kod yuborildi. Kod 5 daqiqa amal qiladi.
            </p>
            <label>
              Kod
              <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                     inputMode="numeric" autoComplete="one-time-code" placeholder="123456" autoFocus required
                     style={{ fontSize: 22, letterSpacing: 6, textAlign: "center" }} />
            </label>
            {info && <div className="alert ok">{info}</div>}
            <button type="submit" disabled={busy || code.length !== 6}>{busy ? "Tekshirilmoqda…" : "Tasdiqlash"}</button>
            <button type="button" className="secondary" onClick={() => {
              setError(""); setInfo("");
              api.post("/api/auth/mfa/resend", { mfa_token: mfaToken }).then(() => setInfo("Yangi kod yuborildi"))
                .catch((e) => setError((e as Error).message));
            }}>Kodni qayta yuborish</button>
            <button type="button" className="secondary" onClick={() => { setMfaToken(null); setCode(""); setError(""); }}>← Orqaga</button>
          </>
        ) : (
          <>
            <label>
              Login
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" autoFocus required />
            </label>
            <label>
              Parol
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
            <button type="submit" disabled={busy}>{busy ? "Kirilmoqda…" : "Kirish"}</button>
          </>
        )}
      </form>
      </div>
    </div>
  );
}
