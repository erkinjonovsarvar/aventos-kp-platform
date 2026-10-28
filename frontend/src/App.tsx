import { useEffect, useRef, useState, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, dateUz, type User } from "./api";
import { useAuth } from "./auth";
import { Logo, ThemeToggle } from "./theme";
import DiscountReport from "./pages/DiscountReport";
import Home from "./pages/Home";
import Dashboard from "./pages/Dashboard";
import { useReminderCount } from "./pages/Reminder";
import Invitations from "./pages/Invitations";
import Issues from "./pages/Issues";
import Join from "./pages/Join";
import Login from "./pages/Login";
import NewQuotation from "./pages/NewQuotation";
import QuotationDetail from "./pages/QuotationDetail";
import QuotationList from "./pages/QuotationList";
import Requests from "./pages/Requests";
import Users from "./pages/Users";
import PriceList from "./pages/PriceList";
import AccountSecurity from "./pages/AccountSecurity";
import SecurityLog from "./pages/SecurityLog";
import AdminGate from "./pages/AdminGate";

function Guard({ any, children }: { any?: string[]; children: ReactNode }) {
  const { user, loading, can } = useAuth();
  const location = useLocation();
  if (loading) return <main><div className="skeleton" style={{ height: 44, width: 260 }} /><div className="skeleton block" /></main>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (any && !can(...any)) return <main><div className="alert err">Bu sahifa uchun ruxsatingiz yo'q.</div></main>;
  return <>{children}</>;
}

const BANNER_KEY = "aventos.mfaBannerHiddenUntil";

function bannerHidden(): boolean {
  try { return Number(window.localStorage.getItem(BANNER_KEY) || 0) > Date.now(); } catch { return false; }
}

function Layout({ children }: { children: ReactNode }) {
  const { user, logout, can, refresh } = useAuth();
  const unset = useReminderCount();
  const location = useLocation();
  const [menu, setMenu] = useState(false);              // telefonda ☰ menyu
  const [adminOpen, setAdminOpen] = useState(false);    // "Admin ▾" ochiladigan menyu
  const [hideBanner, setHideBanner] = useState(bannerHidden);
  const dropRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setMenu(false); setAdminOpen(false); }, [location.pathname]);
  useEffect(() => {
    if (!adminOpen) return;
    const close = (e: MouseEvent) => { if (!dropRef.current?.contains(e.target as Node)) setAdminOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setAdminOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [adminOpen]);

  const showBanner = !!user?.mfa_setup_required && (location.pathname === "/" || !hideBanner);
  const initials = (user?.full_name ?? "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return (
    <>
      <header className={"topbar" + (menu ? " open" : "")}>
        <NavLink to="/" className="brand" title="AVENTOS air design">
          <Logo />
          <span className="tag">KP</span>
        </NavLink>
        <nav aria-label="Asosiy menyu">
          <NavLink to="/" end className="apps-link" title="Bosh sahifa — barcha bo'limlar">▦<span className="m-inline"> Bosh sahifa</span></NavLink>
          {can("dashboard.view") && <NavLink to="/dashboard">Dashboard</NavLink>}
          {can("kp.view_all", "kp.view_own") && (
            <NavLink to="/kp">KP lar{unset > 0 && <span className="nav-dot" title={`${unset} ta KP ga savdo holati belgilanmagan`}>{unset}</span>}</NavLink>
          )}
          {can("discount.report_all", "discount.report_own") && <NavLink to="/reports/discounts">Chegirmalar</NavLink>}
          {can("price.view", "price.manage") && <NavLink to="/prices">Narx ro'yxati</NavLink>}
          {can("data_issue.resolve") && <NavLink to="/issues">Tekshirish kerak</NavLink>}
          {can("user.manage") && (
            <div ref={dropRef} className={"nav-drop" + (adminOpen ? " open" : "") + (location.pathname.startsWith("/admin") ? " active" : "")}>
              <button type="button" className="nav-drop-btn" aria-haspopup="true" aria-expanded={adminOpen}
                      onClick={() => setAdminOpen(!adminOpen)}>Admin ▾</button>
              <div className="nav-drop-menu">
                <span className="m-label">Admin</span>
                <NavLink to="/admin/requests">✉ So'rovlar</NavLink>
                <NavLink to="/admin/users">👥 Foydalanuvchilar</NavLink>
                <NavLink to="/admin/invitations">🔗 Havolalar</NavLink>
                <NavLink to="/admin/security">🛡 Xavfsizlik jurnali</NavLink>
              </div>
            </div>
          )}
          <button type="button" className="secondary m-only" onClick={() => void logout()}>Chiqish</button>
        </nav>
        <span className="who">
          <NavLink to="/account/security" className="who-link" title="Xavfsizlik: Telegram orqali tasdiqlash va faol sessiyalar">
            <span className="avatar" aria-hidden>{initials}</span>
            <span className="who-name" title={user?.access_valid_until ? `Ruxsat ${dateUz(user.access_valid_until)} gacha` : "Muddatsiz"}>
              {user?.full_name}
            </span>
          </NavLink>
          {user?.admin_unlocked && (
            <button className="secondary icon-btn" title="Admin panelni qulflash (keyingi safar maxfiy so'z so'raladi)"
                    onClick={() => void api.post<User>("/api/auth/admin-word/lock").then(() => refresh())}>🔓</button>
          )}
          <ThemeToggle />
          <button className="secondary logout-btn" onClick={() => void logout()}>Chiqish</button>
        </span>
        <button type="button" className="menu-btn" aria-label="Menyu" aria-expanded={menu} onClick={() => setMenu(!menu)}>
          {menu ? "✕" : "☰"}
        </button>
      </header>
      {showBanner && (
        <div className="mfa-banner">
          🔒 Hisobingiz uchun <b>Telegram orqali tasdiqlash</b> majburiy (admin/direktor). <NavLink to="/account/security">Hozir ulash →</NavLink>
          {location.pathname !== "/" && (
            <button className="banner-x" title="24 soatga yashirish" aria-label="Yashirish" onClick={() => {
              try { window.localStorage.setItem(BANNER_KEY, String(Date.now() + 24 * 3600_000)); } catch { /* saqlab bo'lmasa — faqat shu safar */ }
              setHideBanner(true);
            }}>×</button>
          )}
        </div>
      )}
      <main>{children}</main>
    </>
  );
}

export default function App() {
  const page = (node: ReactNode, any?: string[]) => (
    <Guard any={any}>
      <Layout>{node}</Layout>
    </Guard>
  );
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/join/:token" element={<Join />} />
      <Route path="/" element={page(<Home />)} />
      <Route path="/dashboard" element={page(<Dashboard />, ["dashboard.view"])} />
      <Route path="/kp" element={page(<QuotationList />, ["kp.view_all", "kp.view_own"])} />
      <Route path="/kp/new" element={page(<NewQuotation />, ["kp.create_edit"])} />
      <Route path="/kp/:kp" element={page(<QuotationDetail />, ["kp.view_all", "kp.view_own"])} />
      <Route path="/reports/discounts" element={page(<DiscountReport />, ["discount.report_all", "discount.report_own"])} />
      <Route path="/issues" element={page(<Issues />, ["data_issue.resolve"])} />
      <Route path="/prices" element={page(<PriceList />, ["price.view", "price.manage"])} />
      <Route path="/admin/requests" element={page(<AdminGate><Requests /></AdminGate>, ["user.manage"])} />
      <Route path="/admin/users" element={page(<AdminGate><Users /></AdminGate>, ["user.manage"])} />
      <Route path="/admin/invitations" element={page(<AdminGate><Invitations /></AdminGate>, ["user.manage"])} />
      <Route path="/admin/security" element={page(<AdminGate><SecurityLog /></AdminGate>, ["user.manage"])} />
      <Route path="/account/security" element={page(<AccountSecurity />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
