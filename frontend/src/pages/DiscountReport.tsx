import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import DateRange from "./DateRange";
import { api, dateUz, money, pct, qs, type Money } from "../api";

interface ProjectSum {
  project_no: number;
  project_name: string;
  display_currency: string;
  kp_count: string;
  subtotal: Money;
  discount_amount: Money;
  total_after_discount: Money;
  discount_share: string | null;
}

interface Item {
  project_no: number;
  project_name: string;
  kp_number: number;
  revision_no: number;
  kp_date: string;
  manager_name: string;
  display_currency: string;
  annex_no: number;
  annex_name: string;
  subtotal: Money;
  discount_pct: string | null;
  discount_amount: Money;
  total_after_discount: Money;
  discount_by_name: string | null;
  discount_at: string | null;
  discount_reason: string | null;
}

export default function DiscountReport() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [projectNo, setProjectNo] = useState("");
  const [onlyDiscounted, setOnlyDiscounted] = useState(false);
  const [data, setData] = useState<{ by_project: ProjectSum[]; items: Item[] } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<{ by_project: ProjectSum[]; items: Item[] }>(
        "/api/reports/discounts" + qs({ date_from: dateFrom, date_to: dateTo, project_no: projectNo, only_discounted: onlyDiscounted }),
      )
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e.message));
  }, [dateFrom, dateTo, projectNo, onlyDiscounted]);

  const discounted = data?.items.filter((i) => i.discount_pct) ?? [];

  return (
    <>
      <h1>Loyihalar bo'yicha chegirmalar</h1>
      <div className="filters">
        <DateRange from={dateFrom} to={dateTo} onChange={(f, t) => { setDateFrom(f); setDateTo(t); }} />
        <label>Loyiha №<input value={projectNo} onChange={(e) => setProjectNo(e.target.value.replace(/\D/g, ""))} size={8} /></label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={onlyDiscounted} onChange={(e) => setOnlyDiscounted(e.target.checked)} />
          faqat chegirma berilganlar
        </label>
      </div>
      {error && <div className="alert err">{error}</div>}
      {data && (
        <>
          <p className="muted">
            Har KP ning oxirgi tasdiqlangan/yuborilgan revisioni bo'yicha. Chegirma berilgan ilovalar: <b>{discounted.length}</b> ta.
          </p>
          <div className="panel table-wrap">
            <h2 style={{ marginTop: 0 }}>Loyiha jami</h2>
            <table>
              <thead>
                <tr><th>Loyiha</th><th>Valyuta</th><th className="num">KP soni</th><th className="num">Chegirmasiz</th>
                  <th className="num">Chegirma</th><th className="num">Ulushi</th><th className="num">Chegirmadan keyin</th></tr>
              </thead>
              <tbody>
                {data.by_project.map((p) => (
                  <tr key={`${p.project_no}-${p.display_currency}`}>
                    <td>{p.project_name} <span className="muted">#{p.project_no}</span></td>
                    <td>{p.display_currency}</td>
                    <td className="num">{p.kp_count}</td>
                    <td className="num">{money(p.subtotal, p.display_currency)}</td>
                    <td className="num">{Number(p.discount_amount) ? money(p.discount_amount, p.display_currency) : "—"}</td>
                    <td className="num">{Number(p.discount_amount) ? pct(p.discount_share) : "—"}</td>
                    <td className="num">{money(p.total_after_discount, p.display_currency)}</td>
                  </tr>
                ))}
                {data.by_project.length === 0 && <tr><td colSpan={7} className="muted">Ma'lumot yo'q</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="panel table-wrap">
            <h2 style={{ marginTop: 0 }}>Ilovalar bo'yicha</h2>
            <table>
              <thead>
                <tr><th>KP №</th><th>Sana</th><th>Loyiha</th><th>Menejer</th><th>Ilova</th><th className="num">Итого</th>
                  <th className="num">Скидка</th><th className="num">Summa</th><th className="num">Итого со скидкой</th><th>Kim bergan</th><th>Sabab</th></tr>
              </thead>
              <tbody>
                {data.items.map((i) => (
                  <tr key={`${i.kp_number}-${i.annex_no}`}>
                    <td><Link to={`/kp/${i.kp_number}`}>{i.kp_number}</Link></td>
                    <td>{dateUz(i.kp_date)}</td>
                    <td>{i.project_name}</td>
                    <td>{i.manager_name}</td>
                    <td>{i.annex_no}. {i.annex_name}</td>
                    <td className="num">{money(i.subtotal, i.display_currency)}</td>
                    <td className="num">{i.discount_pct ? pct(i.discount_pct) : "—"}</td>
                    <td className="num">{i.discount_pct ? money(i.discount_amount, i.display_currency) : "—"}</td>
                    <td className="num">{money(i.total_after_discount, i.display_currency)} {i.display_currency}</td>
                    <td>{i.discount_by_name ?? ""}{i.discount_at ? <span className="muted"> {dateUz(i.discount_at)}</span> : ""}</td>
                    <td>{i.discount_reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
