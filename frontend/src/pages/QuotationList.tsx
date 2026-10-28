import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, dateUz, money, qs, STATUS_UZ, type QuotationRow } from "../api";
import { useAuth } from "../auth";
import DateRange from "./DateRange";
import { DealPill } from "./DealPanel";
import { DEAL_TRACKING } from "../features";
import Reminder from "./Reminder";

const PAGE = 50;
const STALE_DAYS = 14;               // savdo holati shundan eski va belgilanmagan bo'lsa — sariq (9-band)

interface Manager { id: number; full_name: string; kp_count: number }

const ageDays = (d: string) => (Date.now() - new Date(d).getTime()) / 86_400_000;
const statusCls = (s: string) => (s === "sent" ? "ok" : s === "draft" ? "warn" : "teal");

/** Summa: raqam katta, valyuta kichik va kulrang (16-band). */
function Total({ q }: { q: QuotationRow }) {
  if (q.total_incl_vat === null) return <span className="badge err">narx yo'q ({q.missing_price_lines})</span>;
  return <>{money(q.total_incl_vat, q.display_currency)} <span className="cur">{q.display_currency}</span></>;
}

function Deal({ q }: { q: QuotationRow }) {
  if (q.status === "draft" && !q.deal_status) return <span className="muted">—</span>;
  return <DealPill code={q.deal_status} name={q.deal_status_name} soft={!q.deal_status && ageDays(q.kp_date) < STALE_DAYS} />;
}

export default function QuotationList() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [managerId, setManagerId] = useState("");
  const [status, setStatus] = useState("");
  const [deal, setDeal] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; items: QuotationRow[] } | null>(null);
  const [managers, setManagers] = useState<Manager[]>([]);
  const [deals, setDeals] = useState<{ code: string; name: string }[]>([]);
  const [error, setError] = useState("");
  const [moreFilters, setMoreFilters] = useState(false);     // telefonda qo'shimcha filtrlar yig'ilgan
  const all = can("kp.view_all");

  useEffect(() => {
    if (all) api.get<Manager[]>("/api/quotation-managers").then(setManagers).catch(() => undefined);
    api.get<{ statuses: { code: string; name: string }[] }>("/api/deal/meta").then((m) => setDeals(m.statuses)).catch(() => undefined);
  }, [all]);

  useEffect(() => {
    const t = setTimeout(() => {
      api
        .get<{ total: number; items: QuotationRow[] }>("/api/quotations" + qs({
          search: search.trim(), date_from: dateFrom, date_to: dateTo, manager_id: managerId, status, deal, limit: PAGE, offset,
        }))
        .then((d) => { setData(d); setError(""); })
        .catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [search, dateFrom, dateTo, managerId, status, deal, offset]);

  const reset = (fn: () => void) => { fn(); setOffset(0); };
  const filtered = !!(search || dateFrom || dateTo || managerId || status || deal);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Tijoriy takliflar (KP)</h1>
        {can("kp.create_edit") && <Link to="/kp/new"><button>+ Yangi KP</button></Link>}
      </div>
      <Reminder />
      <div className="panel filterbar">
        <label className="grow">
          Qidiruv (KP №, loyiha nomi yoki raqami)
          <input value={search} onChange={(e) => reset(() => setSearch(e.target.value))} placeholder="masalan 1001880 yoki loyiha nomi" />
        </label>
        <button type="button" className="secondary m-filters-btn" aria-expanded={moreFilters} onClick={() => setMoreFilters(!moreFilters)}>
          ⚙ Filtrlar{[managerId, status, deal, dateFrom || dateTo].filter(Boolean).length ? ` (${[managerId, status, deal, dateFrom || dateTo].filter(Boolean).length})` : ""} {moreFilters ? "▴" : "▾"}
        </button>
        <div className={"extra-filters" + (moreFilters ? " show" : "")}>
        {all && (
          <label>Menejer
            <select value={managerId} onChange={(e) => reset(() => setManagerId(e.target.value))}>
              <option value="">— hammasi —</option>
              {managers.map((m) => <option key={m.id} value={m.id}>{m.full_name} ({m.kp_count})</option>)}
            </select>
          </label>
        )}
        <label>KP holati
          <select value={status} onChange={(e) => reset(() => setStatus(e.target.value))}>
            <option value="">— hammasi —</option>
            {Object.entries(STATUS_UZ).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {DEAL_TRACKING && <label>Savdo holati
          <select value={deal} onChange={(e) => reset(() => setDeal(e.target.value))}>
            <option value="">— hammasi —</option>
            <option value="unset">Belgilanmagan</option>
            {deals.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
          </select>
        </label>}
        <DateRange from={dateFrom} to={dateTo} onChange={(f, t) => reset(() => { setDateFrom(f); setDateTo(t); })} />
        </div>
      </div>
      {error && <div className="alert err">{error}</div>}
      {!data && <><div className="skeleton row" /><div className="skeleton block" /></>}
      {data && (
        <>
          <div className="row list-meta">
            <span>Topildi: <b>{data.total}</b> ta KP</span>
            {filtered && (
              <button className="secondary small" onClick={() => {
                setSearch(""); setDateFrom(""); setDateTo(""); setManagerId(""); setStatus(""); setDeal(""); setOffset(0);
              }}>✕ Filtrlarni tozalash</button>
            )}
          </div>
          <div className="panel table-wrap desktop-only">
            <table>
              <thead>
                <tr>
                  <th>KP №</th><th>Sana</th><th>Loyiha</th><th>Menejer</th><th>Rev</th><th>Holat</th>{DEAL_TRACKING && <th>Savdo</th>}
                  <th className="num">Ilova</th><th className="num">Chegirma</th><th className="num">Jami (QQS bilan)</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((q) => (
                  <tr key={q.kp_number} className="clickable" onClick={() => navigate(`/kp/${q.kp_number}`)}>
                    <td><b>{q.kp_number}</b></td>
                    <td>{dateUz(q.kp_date)}</td>
                    <td>{q.project_name} <span className="muted">#{q.project_no}</span></td>
                    <td>{q.manager_name}</td>
                    <td>{q.revision_no}</td>
                    <td><span className={`badge ${statusCls(q.status)}`}>{STATUS_UZ[q.status] ?? q.status}</span></td>
                    {DEAL_TRACKING && <td><Deal q={q} /></td>}
                    <td className="num">{q.annex_count}</td>
                    <td className="num">{Number(q.discount_amount) ? <>{money(q.discount_amount, q.display_currency)} <span className="cur">{q.display_currency}</span></> : "—"}</td>
                    <td className="num" title={q.total_incl_vat ?? "Narxi noma'lum qator bor"}><Total q={q} /></td>
                  </tr>
                ))}
                {data.items.length === 0 && <tr><td colSpan={DEAL_TRACKING ? 10 : 9} className="muted">Hech narsa topilmadi</td></tr>}
              </tbody>
            </table>
          </div>
          {/* Telefonda — kartochkalar (3-band) */}
          <div className="kp-cards mobile-only">
            {data.items.map((q) => (
              <Link key={q.kp_number} to={`/kp/${q.kp_number}`} className="kp-card">
                <span className="kp-card-top">
                  <b>№ {q.kp_number}{q.revision_no > 1 ? ` · R${q.revision_no}` : ""}</b>
                  <span className="muted">{dateUz(q.kp_date)}</span>
                </span>
                <span className="kp-card-name">{q.project_name}</span>
                <span className="muted">{q.manager_name}</span>
                <span className="kp-card-foot">
                  <span className={`badge ${statusCls(q.status)}`}>{STATUS_UZ[q.status] ?? q.status}</span>
                  {DEAL_TRACKING && <Deal q={q} />}
                  <b className="kp-card-sum"><Total q={q} /></b>
                </span>
              </Link>
            ))}
            {data.items.length === 0 && <p className="muted">Hech narsa topilmadi</p>}
          </div>
          <div className="pager">
            <button className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Oldingi</button>
            <span className="muted">{data.total ? `${offset + 1}–${Math.min(offset + PAGE, data.total)} / ${data.total}` : "0"}</span>
            <button className="secondary" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Keyingi →</button>
          </div>
        </>
      )}
    </>
  );
}
