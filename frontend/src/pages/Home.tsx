import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, dateUz, money, STATUS_UZ, type QuotationRow } from "../api";
import { useAuth } from "../auth";
import Reminder from "./Reminder";

interface Tile { to: string; icon: string; title: string; text: string; color: string; badge?: string | number; show: boolean; admin?: boolean }

function greeting() {
  const h = new Date().getHours();
  return h < 11 ? "Xayrli tong" : h < 18 ? "Xayrli kun" : "Xayrli kech";
}

/** Bosh sahifa (Odoo kabi): avval ilovalar paneli — kerakli bo'lim tanlanadi, ish ketma-ket davom etadi. */
export default function Home() {
  const { user, can } = useAuth();
  const navigate = useNavigate();
  const [recent, setRecent] = useState<QuotationRow[]>([]);
  const [drafts, setDrafts] = useState<number | null>(null);
  const [issues, setIssues] = useState<number | null>(null);
  const [requests, setRequests] = useState<number | null>(null);

  useEffect(() => {
    if (can("kp.view_all", "kp.view_own")) {
      api.get<{ total: number; items: QuotationRow[] }>("/api/quotations?limit=60").then((d) => {
        setRecent(d.items.slice(0, 6));
        setDrafts(d.items.filter((q) => q.status === "draft").length);
      }).catch(() => undefined);
    }
    if (can("data_issue.resolve")) api.get<unknown[]>("/api/data-issues?open_only=true").then((x) => setIssues(x.length)).catch(() => undefined);
    if (can("user.manage")) api.get<unknown[]>("/api/admin/access-requests?status_=pending").then((x) => setRequests(x.length)).catch(() => undefined);
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const tiles: Tile[] = [
    { to: "/dashboard", icon: "📊", title: "Dashboard", text: "KP lar soni va summasi — kun, oy, chorak, yil kesimida", color: "#7a6ff0",
      show: can("dashboard.view") },
    { to: "/kp/new", icon: "✚", title: "Yangi KP", text: "Qadam-baqadam: manba → loyiha → menejer → yaratish", color: "#3cc6cf", show: can("kp.create_edit") },
    { to: "/kp", icon: "📄", title: "KP lar", text: "Barcha tijoriy takliflar, qidiruv va revisionlar", color: "#4b5a70",
      badge: drafts ? `${drafts} qoralama` : undefined, show: can("kp.view_all", "kp.view_own") },
    { to: "/reports/discounts", icon: "％", title: "Chegirmalar", text: "Loyihalar bo'yicha berilgan chegirmalar", color: "#d9a91a", show: can("discount.report_all", "discount.report_own") },
    { to: "/prices", icon: "🏷", title: "Narx ro'yxati", text: "Mahsulotlar va narxlar: yangi mahsulot qo'shish, narxni yangilash", color: "#3a7d5c",
      show: can("price.view", "price.manage") },
    { to: "/issues", icon: "⚑", title: "Tekshirish kerak", text: "Eski bazadan ko'chirishdagi noaniqliklar — ko'rib chiqish", color: "#e07a5f", badge: issues ? `${issues} ta` : undefined, show: can("data_issue.resolve") },
    { to: "/admin/requests", icon: "✉", title: "So'rovlar", text: "Yangi xodimlarning kirish so'rovlari", color: "#7a6ff0", badge: requests || undefined, show: can("user.manage"), admin: true },
    { to: "/admin/users", icon: "👥", title: "Foydalanuvchilar", text: "Rollar, ruxsatlar va muddatlar", color: "#2f9fa8", show: can("user.manage"), admin: true },
    { to: "/admin/invitations", icon: "🔗", title: "Havolalar", text: "Taklif havolasini yaratish", color: "#5b8def", show: can("user.manage"), admin: true },
    { to: "/admin/security", icon: "🛡", title: "Xavfsizlik jurnali", text: "Kirishlar, noto'g'ri urinishlar va bloklar", color: "#c0504d", show: can("user.manage"), admin: true },
    { to: "/account/security", icon: "🔒", title: "Mening xavfsizligim", text: "Telegram orqali tasdiqlash va faol qurilmalar", color: "#3a7d5c",
      badge: user?.mfa_setup_required ? "ulang" : undefined, show: true },
  ];

  return (
    <div className="home">
      <div className="home-hello">
        <div>
          <div className="muted">{greeting()},</div>
          <h1 className="plain">{user?.full_name}</h1>
        </div>
        {can("kp.create_edit") && <button onClick={() => navigate("/kp/new")}>✚ Yangi KP tayyorlash</button>}
      </div>

      <Reminder />
      {[false, true].map((adm) => {
        const list = tiles.filter((t) => t.show && !!t.admin === adm);
        if (!list.length) return null;
        return (
          <section key={String(adm)}>
            {tiles.some((t) => t.show && t.admin) && <h2 className="apps-head">{adm ? "Boshqaruv" : "Ish"}</h2>}
            <div className={"apps" + (adm ? " small" : "")}>
              {list.map((t) => (
                <Link key={t.to} to={t.to} className="app-tile" style={{ ["--tile" as string]: t.color }}>
                  <span className="app-icon">{t.icon}</span>
                  <span className="app-title">{t.title}</span>
                  <span className="app-text">{t.text}</span>
                  {t.badge !== undefined && <span className="app-badge">{t.badge}</span>}
                </Link>
              ))}
            </div>
          </section>
        );
      })}

      {recent.length > 0 && (
        <div className="panel">
          <div className="section-head">
            <h2>Oxirgi KP lar</h2>
            <Link to="/kp">Hammasini ko'rish →</Link>
          </div>
          <div className="recent">
            {recent.map((q) => (
              <Link key={q.kp_number} to={`/kp/${q.kp_number}`} className="recent-card">
                <span className="recent-no">№ {q.kp_number}{q.revision_no > 1 ? ` · R${q.revision_no}` : ""}</span>
                <span className="recent-name">{q.project_name}</span>
                <span className="muted">{q.manager_name} · {dateUz(q.kp_date)}</span>
                <span className="recent-foot">
                  <span className={`badge ${q.status === "sent" ? "ok" : q.status === "draft" ? "warn" : "teal"}`}>{STATUS_UZ[q.status] ?? q.status}</span>
                  <b>{money(q.total_incl_vat, q.display_currency)} {q.display_currency}</b>
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
