import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** Parol to'g'ri bo'lsa: Telegram ulangan foydalanuvchi uchun mfa_token qaytadi (kod Telegram'ga ketdi), aks holda kirildi. */
  login: (login: string, password: string) => Promise<{ token: string; telegram: string | null } | null>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  can: (...permissions: string[]) => boolean;
  /** Bot ichida (Telegram Mini App) avtomatik kirish bo'lmagan bo'lsa — sababi (login sahifasida ko'rsatiladi). */
  telegramError: string | null;
}

const AuthContext = createContext<AuthState | null>(null);

/** Platforma Telegram bot ichida ochilganda Telegram manzil oxiriga imzolangan ma'lumot qo'shadi (#tgWebAppData=...).
 *  Sahifa qayta yuklansa ham ishlashi uchun sessionStorage da saqlanadi (imzo 1 soat amal qiladi). */
function telegramInitData(): string | null {
  try {
    const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData");
    if (fromHash) {
      sessionStorage.setItem("tgWebAppData", fromHash);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      return fromHash;
    }
    return sessionStorage.getItem("tgWebAppData");
  } catch {
    return null;
  }
}

/** Sahifa Telegram bot ichida (Mini App) ochilganmi — u yerda fayl yuklab olib bo'lmaydi, fayllar bot chatiga yuboriladi. */
export function inTelegram(): boolean {
  try {
    return !!sessionStorage.getItem("tgWebAppData") || window.location.hash.includes("tgWebAppData");
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [telegramError, setTelegramError] = useState<string | null>(null);

  useEffect(() => {
    const initData = telegramInitData();
    api
      .get<User>("/api/auth/me")
      .then(setUser)
      .catch(async (e) => {
        if (!(e instanceof ApiError && e.status === 401)) return console.error(e);
        if (!initData) return;
        try {
          // bot ichida: Telegram imzosi bilan avtomatik kirish (foydalanuvchi qarori 2026-10-21)
          setUser(await api.post<User>("/api/auth/telegram/webapp", { init_data: initData }));
        } catch (err) {
          setTelegramError((err as Error).message);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (loginName: string, password: string) => {
    const r = await api.post<User & { mfa_required?: boolean; mfa_token?: string }>("/api/auth/login", { login: loginName, password });
    if (r.mfa_required && r.mfa_token) return { token: r.mfa_token, telegram: r.telegram_name ?? null };
    setUser(r);
    return null;
  }, []);

  const verifyMfa = useCallback(async (mfaToken: string, code: string) => {
    setUser(await api.post<User>("/api/auth/mfa", { mfa_token: mfaToken, code }));
  }, []);

  const refresh = useCallback(async () => {
    setUser(await api.get<User>("/api/auth/me"));
  }, []);

  useEffect(() => {
    const onLocked = () => { api.get<User>("/api/auth/me").then(setUser).catch(() => setUser(null)); };
    window.addEventListener("admin-locked", onLocked);
    return () => window.removeEventListener("admin-locked", onLocked);
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setUser(null);
  }, []);

  const can = useCallback((...permissions: string[]) => !!user && permissions.some((p) => user.permissions.includes(p)), [user]);

  return <AuthContext.Provider value={{ user, loading, login, verifyMfa, refresh, logout, can, telegramError }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("AuthProvider yo'q");
  return ctx;
}
