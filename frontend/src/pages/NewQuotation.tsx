import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, dateUz, money, qs } from "../api";
import { useAuth } from "../auth";

interface OfferItem {
  id: number; source_row: number; block_code: string; unit_label: string | null; model: string | null;
  description: string | null; air_flow: string | null; flow_kg_h: string | null; quantity: string; unit_price: string;
  parent_label: string | null; price_list_price?: string | null;
}
interface Offer {
  id: number; project_name_raw: string | null; offer_date: string | null; file_name: string;
  items: OfferItem[]; warnings?: string[]; hidden_rows?: number;
  project_suggestions: Project[];
}
interface Project { id: number; project_no: number; name: string }
interface Orphan { row: number; block: string; label: string | null; model: string | null }
interface OrphanFix { file: File; message: string; orphans: Orphan[]; ahu: { row: number; label: string | null; model: string | null }[]; choice: Record<number, string> }
interface Employee { id: number; full_name: string }
interface Rate { id: number; rate: string; rate_date: string; source: string }

const BLOCK_UZ: Record<string, string> = { AHU: "AHU", AUTOMATION: "Automation", VRF: "VRF", KIT: "AHU kit", VALVE: "3-way valve" };

export default function NewQuotation() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [offer, setOffer] = useState<Offer | null>(null);
  const [uploading, setUploading] = useState(false);
  const [projectSearch, setProjectSearch] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [managerId, setManagerId] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [rates, setRates] = useState<Rate[]>([]);
  const [rateId, setRateId] = useState("");
  const [annexName, setAnnexName] = useState("AHU");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const [orphanFix, setOrphanFix] = useState<OrphanFix | null>(null);
  const [source, setSource] = useState<"ahu" | "catalog" | "">("");

  useEffect(() => {
    api.get<Employee[]>("/api/employees").then(setEmployees).catch((e) => setError(e.message));
    api.get<Rate[]>("/api/exchange-rates").then(setRates).catch(() => undefined);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => {
      api.get<Project[]>("/api/projects" + qs({ search: projectSearch.trim() })).then(setProjects).catch(() => undefined);
    }, 250);
    return () => clearTimeout(t);
  }, [projectSearch]);

  async function onFile(file: File | undefined, fixes?: Record<number, string>) {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const o = await api.upload<Offer>("/api/ahu-offers" + qs({ fixes: fixes ? JSON.stringify(fixes) : undefined }), file);
      setOrphanFix(null);
      setOffer(o);
      setAnnexName("AHU");
      const raw = (o.project_name_raw ?? "").trim();
      if (o.project_suggestions.length === 1) setProject(o.project_suggestions[0]);
      setProjectSearch(raw);
    } catch (e) {
      const d = e instanceof ApiError ? (e.data as Partial<OrphanFix> | undefined) : undefined;
      if (d && Array.isArray(d.orphans) && Array.isArray(d.ahu)) {
        // A ustunidagi yorliq hech bir AHU ga mos emas — taxmin qilinmaydi, foydalanuvchi tanlaydi
        setOrphanFix({ file, message: (e as Error).message, orphans: d.orphans, ahu: d.ahu, choice: {} });
        setOffer(null);
      } else {
        setError((e as Error).message);
      }
    } finally {
      setUploading(false);
    }
  }

  async function createProject() {
    const name = projectSearch.trim();
    if (!name) return;
    try {
      setProject(await api.post<Project>("/api/projects", { name }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function create() {
    if (!project || !managerId) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.post<{ kp_number: number; warnings: string[] }>("/api/quotations", {
        project_id: project.id, manager_id: Number(managerId), ahu_offer_id: offer?.id ?? null,
        annex_name: annexName, display_currency: currency, exchange_rate_id: rateId ? Number(rateId) : null,
      });
      navigate(`/kp/${r.kp_number}`, { state: { warnings: r.warnings } });
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const visible = offer?.items ?? [];
  const managerName = employees.find((e) => String(e.id) === managerId)?.full_name;
  const steps = ["Manba", "Loyiha", "Menejer va valyuta", "Tekshirish"];
  const canNext = [
    source === "catalog" || (source === "ahu" && !!offer),
    !!project,
    !!managerId && (currency !== "UZS" || !!rateId) && (!!offer || !!annexName.trim()),
    true,
  ];
  return (
    <>
      <div className="breadcrumb"><Link to="/">Bosh sahifa</Link> / <Link to="/kp">KP lar</Link> / <b>Yangi KP</b></div>
      <h1>Yangi KP</h1>
      <ol className="stepper">
        {steps.map((t, i) => (
          <li key={t} className={i < step ? "done" : i === step ? "on" : ""} onClick={() => { if (i < step) setStep(i); }}>
            <span className="dot">{i < step ? "✓" : i + 1}</span><span>{t}</span>
          </li>
        ))}
      </ol>
      {error && <div className="alert err">{error}</div>}

      {step === 0 && (
        <div className="panel">
          <h2>KP qanday tuzilsin?</h2>
          <div className="choice-grid">
            <button className={"choice" + (source === "ahu" ? " on" : "")} disabled={!can("ahu.import")} onClick={() => { setSource("ahu"); setAnnexName("AHU"); }}>
              <span className="choice-icon">🌀</span><b>AHU faylidan</b>
              <span className="muted">Zavoddan kelgan quotation.xlsx — AHU, automation, VRF, kit va valve avtomatik</span>
            </button>
            <button className={"choice" + (source === "catalog" ? " on" : "")} onClick={() => { setSource("catalog"); setOffer(null); if (annexName === "AHU") setAnnexName(""); setStep(1); /* 10: darhol keyingi qadam */ }}>
              <span className="choice-icon">📦</span><b>Katalogdan</b>
              <span className="muted">Bo'sh KP: VRF, chiller, fankoil va boshqalarni tur va kW bo'yicha tanlab qo'shasiz</span>
            </button>
          </div>
          {source === "ahu" && (
            <div style={{ marginTop: 16 }}>
              <label>AHU fayli (.xlsx)
                <input type="file" accept=".xlsx" disabled={uploading} onChange={(e) => void onFile(e.target.files?.[0])} />
              </label>
              {uploading && <p className="muted">O'qilmoqda…</p>}
              {orphanFix && (
                <div className="prompt" style={{ display: "block" }}>
                  <b>Faylda {orphanFix.orphans.length} ta qatorning AHU yorlig'i (A ustuni) hech bir AHU ga mos kelmadi.</b>
                  <p className="muted" style={{ margin: "4px 0 10px" }}>Ko'pincha bu yozuv xatosi (masalan П1 o'rniga П2). Har biri qaysi AHU ga tegishli ekanini tanlang — fayl o'zgarmaydi, tanlov KP manbasida qayd etiladi.</p>
                  <table>
                    <thead><tr><th>Qator</th><th>Blok</th><th>Model</th><th>Fayldagi yorliq</th><th>Qaysi AHU ga tegishli?</th></tr></thead>
                    <tbody>
                      {orphanFix.orphans.map((o) => (
                        <tr key={o.row}>
                          <td>{o.row}</td><td><span className="badge">{BLOCK_UZ[o.block] ?? o.block}</span></td><td>{o.model}</td>
                          <td><span className="badge warn">{o.label ?? "bo'sh"}</span></td>
                          <td>
                            <select value={orphanFix.choice[o.row] ?? ""}
                                    onChange={(e) => setOrphanFix({ ...orphanFix, choice: { ...orphanFix.choice, [o.row]: e.target.value } })}>
                              <option value="">— tanlang —</option>
                              {orphanFix.ahu.map((a) => <option key={a.row} value={a.row}>{a.label} — {a.model} ({a.row}-qator)</option>)}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="row" style={{ marginTop: 10 }}>
                    <button className="accent" disabled={uploading || orphanFix.orphans.some((o) => !orphanFix.choice[o.row])}
                            onClick={() => void onFile(orphanFix.file, orphanFix.choice)}>Bog'lab davom etish</button>
                    <button className="secondary" onClick={() => setOrphanFix(null)}>Bekor qilish (faylni tuzataman)</button>
                  </div>
                </div>
              )}
              {offer && (
                <div style={{ marginTop: 12 }}>
                  <p>
                    <b>{offer.file_name}</b> — loyiha: <b>{offer.project_name_raw}</b>, sana: {dateUz(offer.offer_date)}
                    {offer.hidden_rows !== undefined && <span className="muted"> · yashirin qatorlar: {offer.hidden_rows}</span>}
                  </p>
                  {offer.warnings?.map((w) => <div className="alert warn" key={w}>{w}</div>)}
                  <div className="table-wrap" style={{ maxHeight: 340, overflowY: "auto" }}>
                    <table>
                      <thead><tr><th>Qator</th><th>Blok</th><th>AHU</th><th>Model</th><th>Tavsif</th><th className="num">Soni</th><th className="num">Narx (fayl)</th><th className="num">Narx ro'yxati</th></tr></thead>
                      <tbody>
                        {visible.map((i) => (
                          <tr key={i.id}>
                            <td>{i.source_row}</td>
                            <td><span className="badge">{BLOCK_UZ[i.block_code] ?? i.block_code}</span></td>
                            <td>{i.unit_label ?? i.parent_label ?? <span className="badge err">bog'lanmagan</span>}</td>
                            <td>{i.model ?? ""}</td>
                            <td className="desc">{i.description ?? ""}</td>
                            <td className="num">{i.quantity}</td>
                            <td className="num">{money(i.unit_price)}</td>
                            <td className="num">
                              {i.block_code === "VRF" || i.block_code === "KIT"
                                ? (i.price_list_price ? money(i.price_list_price) : <span className="badge err">yo'q</span>)
                                : ""}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted">VRF va AHU kit narxi narx ro'yxatidan (marjasiz). AHU narxi = AHU + automation; marja KP sahifasida har qatorga alohida.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {step === 1 && (
        <div className="panel">
          <h2>Loyiha</h2>
          <div className="row" style={{ marginBottom: 10 }}>
            <label>Loyihani qidirish
              <input value={projectSearch} onChange={(e) => { setProjectSearch(e.target.value); setProject(null); }} size={40} placeholder="nomi yoki raqami" autoFocus />
            </label>
            {can("project.manage") && !project && projectSearch.trim().length > 1 && (
              <button className="secondary" onClick={() => void createProject()}>"{projectSearch.trim()}" — yangi loyiha yaratish</button>
            )}
          </div>
          {project
            ? <div className="alert ok">Tanlandi: <b>{project.name}</b> #{project.project_no} <button className="secondary small" onClick={() => setProject(null)}>O'zgartirish</button></div>
            : (
              <div className="table-wrap" style={{ maxHeight: 260, overflowY: "auto" }}>
                <table>
                  <tbody>
                    {projects.map((p) => (
                      <tr key={p.id} className="clickable" onClick={() => setProject(p)}><td style={{ width: 80 }}>#{p.project_no}</td><td>{p.name}</td></tr>
                    ))}
                    {projects.length === 0 && <tr><td className="muted">Topilmadi</td></tr>}
                  </tbody>
                </table>
              </div>
            )}
        </div>
      )}

      {step === 2 && (
        <div className="panel">
          <h2>Menejer va valyuta</h2>
          <div className="row">
            <label>Menejer
              <select value={managerId} onChange={(e) => setManagerId(e.target.value)} autoFocus>
                <option value="">— tanlang —</option>
                {employees.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
              </select>
            </label>
            <label>Valyuta
              <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                <option value="USD">USD</option><option value="UZS">UZS (so'm)</option>
              </select>
            </label>
            {currency === "UZS" && (
              <label>Tasdiqlangan kurs
                <select value={rateId} onChange={(e) => setRateId(e.target.value)}>
                  <option value="">— tanlang —</option>
                  {rates.map((r) => <option key={r.id} value={r.id}>{r.rate} ({dateUz(r.rate_date)}, {r.source.slice(0, 40)})</option>)}
                </select>
              </label>
            )}
            {!offer && (
              <label>1-ilova nomi<input value={annexName} onChange={(e) => setAnnexName(e.target.value)} placeholder="masalan VRF" /></label>
            )}
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="panel">
          <h2>Tekshiring va yarating</h2>
          <dl className="kv">
            <dt>Manba</dt><dd>{offer ? <>AHU fayli — <b>{offer.file_name}</b> ({visible.length} qator)</> : "Katalogdan (bo'sh KP)"}</dd>
            <dt>Loyiha</dt><dd><b>{project?.name}</b> #{project?.project_no}</dd>
            <dt>Menejer</dt><dd>{managerName}</dd>
            <dt>Valyuta</dt><dd>{currency}</dd>
            <dt>1-ilova</dt><dd>{offer ? "AHU" : annexName}</dd>
            <dt>KP raqami</dt><dd className="muted">avtomatik (eng kichik bo'sh raqam), sana — bugun</dd>
          </dl>
          <p className="muted" style={{ marginBottom: 0 }}>
            Keyingi qadam KP sahifasida: {offer ? "har AHU/valve qatoriga marja kiritish" : "katalogdan mahsulot qo'shish"} → tekshirish → tasdiqlash → Excel.
          </p>
        </div>
      )}

      <div className="wizard-nav">
        <button className="secondary" onClick={() => (step === 0 ? navigate(-1) : setStep(step - 1))}>← {step === 0 ? "Bekor qilish" : "Orqaga"}</button>
        {step < 3
          ? <button disabled={!canNext[step]} onClick={() => setStep(step + 1)}>Keyingi →</button>
          : <button className="accent" disabled={busy} onClick={() => void create()}>{busy ? "Yaratilmoqda…" : "✓ KP yaratish (qoralama)"}</button>}
      </div>
    </>
  );
}
