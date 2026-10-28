import { Fragment, useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, dateUz, fractionToPct, money, pct, pctToFraction, qs, STATUS_UZ, type Money } from "../api";
import { inTelegram, useAuth } from "../auth";
import { copyText, toast } from "../toast";
import BulkAdd, { type MergedLine } from "./BulkAdd";
import AhuUpload from "./AhuUpload";
import AccessoryPrompt from "./AccessoryPrompt";
import CatalogPicker from "./CatalogPicker";
import DealPanel from "./DealPanel";
import { DEAL_TRACKING } from "../features";

interface Line {
  line_id: number;
  line_type: string;
  annex_id: number;
  line_no: number;
  category: string | null;
  model: string | null;
  description: string | null;
  performance: string | null;
  performance_unit: string | null;
  quantity: string;
  unit_code: string | null;
  unit_price_excl_vat?: Money;
  unit_price_incl_vat: Money;
  display_unit_price: Money;
  display_line_total: Money;
  margin_pct?: string | null;
  // mahsulot chegirmasi (0025): net — chegirmali narx, QQS bilan narxdan ROUNDUP
  display_unit_net: Money;
  display_line_net: Money;
  line_discount_kind: "pct" | "amount" | null;
  line_discount_value: string | null;
  line_discount_reason: string | null;
  evidence_count: number;
}

interface Evidence {
  id: number;
  file_name: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
  uploaded_by_name: string;
  line_ids: number[];
  annex_ids: number[];
}

interface Annex {
  annex_id: number;
  annex_no: number;
  name: string;
  subtotal: Money;
  total_quantity: string;
  missing_price_lines: string;
  discount_pct: string | null;
  discount_amount: Money;
  total_after_discount: Money;
  discount_reason: string | null;
  line_discount_amount: Money;
  net_subtotal: Money;
  evidence_count: number;
  lines: Line[];
}

interface Detail {
  kp_number: number;
  project_no: number;
  project_name: string;
  manager_name: string;
  manager_phone: string | null;
  revisions: { revision_no: number; kp_date: string; status: string }[];
  totals: {
    revision_no: number;
    status: string;
    kp_date: string;
    valid_until: string;
    display_currency: string;
    annex_count: string;
    subtotal: Money;
    discount_amount: Money;
    total_incl_vat: Money;
    total_excl_vat_info: Money;
    vat_amount_info: Money;
    show_excl_vat_note: boolean;
    missing_price_lines: string;
    editable: boolean;
  };
  annexes: Annex[];
  exchange_rate: { id: number; rate: string; rate_date: string; source: string } | null;
  currency_changes: { changed_at: string; status_at_change: string; old_currency: string; old_rate: string | null;
                      new_currency: string; new_rate: string | null; changed_by_name: string }[];
}

interface Rate { id: number; rate: string; rate_date: string; source: string }

/** Valyutani almashtirish (0028, foydalanuvchi qarori 2026-10-28): tayyor (tasdiqlangan/yuborilgan) KP da ham, shu revisionning
 *  o'zida — revision raqami va holati o'zgarmaydi. Kurs har safar tasdiqlangan kurslar ro'yxatidan tanlanadi. */
function CurrencyEditor({ kp, revisionNo, cur, rateId, ready, onSaved }:
  { kp: number; revisionNo: number; cur: string; rateId: number | null; ready: boolean; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [currency, setCurrency] = useState(cur);
  const [rate, setRate] = useState(rateId ? String(rateId) : "");
  const [rates, setRates] = useState<Rate[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (open) api.get<Rate[]>("/api/exchange-rates").then(setRates).catch((e) => setError((e as Error).message));
  }, [open]);
  if (!open) return <button className="secondary small" onClick={() => { setCurrency(cur); setRate(rateId ? String(rateId) : ""); setError(""); setOpen(true); }}>Valyutani o'zgartirish</button>;
  async function save() {
    if (ready && !window.confirm(`KP tayyor (tasdiqlangan/yuborilgan). Valyuta shu revisionning o'zida ${currency} ga almashtirilsinmi? Kim va qachon almashtirgani tarixga yoziladi.`)) return;
    setError("");
    try {
      await api.put(`/api/quotations/${kp}/currency`,
        { display_currency: currency, exchange_rate_id: currency === "UZS" ? Number(rate) : null, revision_no: revisionNo });
      toast(`Valyuta: ${currency}`);
      setOpen(false);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <span className="row">
      <select value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label="Valyuta">
        <option value="USD">USD</option><option value="UZS">UZS (so'm)</option>
      </select>
      {currency === "UZS" && (
        <select value={rate} onChange={(e) => setRate(e.target.value)} aria-label="Tasdiqlangan kurs">
          <option value="">— tasdiqlangan kurs —</option>
          {rates.map((r) => <option key={r.id} value={r.id}>{r.rate} ({dateUz(r.rate_date)}, {r.source.slice(0, 40)})</option>)}
        </select>
      )}
      <button disabled={currency === "UZS" && !rate} onClick={() => void save()}>Saqlash</button>
      <button className="secondary" onClick={() => setOpen(false)}>Bekor</button>
      {error && <span className="err-text">{error}</span>}
    </span>
  );
}

const COVER_UZ: Record<string, string> = { ahu: "AVENTOS (AHU) muqova", vrf: "Hisense VRF muqova", none: "eski muqova" };

/** Excel: 1-sahifada yangi muqova (jadval bilan bir xil enda). Muqova avtomatik (faqat AHU+valve / faqat VRF), aks holda tanlanadi.
 *  PDF yuklab olish hozircha yashirilgan (foydalanuvchi qarori 2026-10-17: faqat Excel). */
function ExcelButton({ kp, revisionNo, annexCount, hasLineDiscount }:
  { kp: number; revisionNo: number; annexCount: number; hasLineDiscount: boolean }) {
  const [auto, setAuto] = useState<string | null | undefined>(undefined);
  const [choice, setChoice] = useState("none");
  const [vatSeparate, setVatSeparate] = useState(false);       // "NDS alohida ko'rsatilsinmi?" (2026-10-17)
  const [annexPages, setAnnexPages] = useState(false);         // "Har ilova alohida sahifada" (2026-10-22)
  // Mahsulot chegirmasi (2026-10-22): ko'rinsin — asosiy narx + pastda chegirma; ko'rinmasin — kataklarda darhol chegirmali narx
  const [lineDiscVisible, setLineDiscVisible] = useState(true);
  useEffect(() => {
    api.get<{ auto: string | null }>(`/api/quotations/${kp}/cover` + qs({ revision_no: revisionNo }))
      .then((r) => { setAuto(r.auto); setChoice(r.auto ?? "none"); }).catch(() => setAuto(null));
  }, [kp, revisionNo]);
  const [sending, setSending] = useState(false);
  const params = qs({ revision_no: revisionNo, cover: auto === undefined ? "auto" : choice, vat_separate: vatSeparate || undefined,
    annex_pages: (annexCount > 1 && annexPages) || undefined,
    line_discount_visible: hasLineDiscount && !lineDiscVisible ? false : undefined });
  const href = `/api/quotations/${kp}/export.xlsx` + params;
  // Bot ichida (Telegram Mini App) fayl yuklab olinmaydi — Excel bot chatiga yuboriladi (2026-10-21)
  async function sendToChat() {
    setSending(true);
    toast("Excel tayyorlanmoqda va bot chatiga yuborilmoqda…", "warn");
    try {
      await api.post(`/api/quotations/${kp}/send-telegram` + params);
      toast("Excel bot chatiga yuborildi — chatni oching");
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setSending(false);
    }
  }
  return (
    <span className="pdf-btn">
      {inTelegram() ? (
        <button className="secondary" disabled={sending} onClick={() => void sendToChat()}>
          {sending ? "Yuborilmoqda…" : "📤 Excel'ni chatga yuborish"}
        </button>
      ) : (
        <a href={href} download onClick={() => { if (choice !== "none") toast("Excel tayyorlanmoqda (muqova bilan, ~5 soniya)…", "warn"); }}>
          <button className="secondary">⬇ Excel yuklab olish</button>
        </a>
      )}
      {auto !== undefined && (
        <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Excel muqovasi"
                title={auto ? "Muqova avtomatik tanlandi" : "Bu KP uchun muqovani tanlang (aralash yoki boshqa jihozlar)"}>
          {["ahu", "vrf", "none"].map((k) => <option key={k} value={k}>{COVER_UZ[k]}{k === auto ? " ✓" : ""}</option>)}
        </select>
      )}
      <label className="vat-toggle" title="Narxlar QQSsiz, pastida «НДС, 12%» va «Сумма с НДС» alohida qatorda">
        <input type="checkbox" checked={vatSeparate} onChange={(e) => setVatSeparate(e.target.checked)} /> NDS alohida
      </label>
      {annexCount > 1 && (
        <label className="vat-toggle" title="Chop etishda (PDF) har ilova yangi sahifadan boshlanadi">
          <input type="checkbox" checked={annexPages} onChange={(e) => setAnnexPages(e.target.checked)} /> Har ilova alohida sahifada
        </label>
      )}
      {hasLineDiscount && (
        <label className="vat-toggle" title="Belgilangan: jadvalda asosiy sotuv narxi, pastda «Скидка на отдельные позиции». Belgisiz: kataklarda darhol chegirmali narx, pastda chegirma yozilmaydi">
          <input type="checkbox" checked={lineDiscVisible} onChange={(e) => setLineDiscVisible(e.target.checked)} /> Mahsulot chegirmasi ko'rinsin
        </label>
      )}
    </span>
  );
}

function MarginInput({ kp, line, onSaved, onError }: { kp: number; line: Line; onSaved: (fraction?: string) => void; onError: (m: string) => void }) {
  const [v, setV] = useState(fractionToPct(line.margin_pct));
  useEffect(() => setV(fractionToPct(line.margin_pct)), [line.margin_pct]);
  async function save() {
    if (v === fractionToPct(line.margin_pct)) return;
    const f = pctToFraction(v);
    if (f === null) return onError("Marja — son bo'lishi kerak (masalan 10 yoki 12.5)");
    try {
      await api.patch(`/api/quotations/${kp}/lines/${line.line_id}`, { margin_pct: f });
      onSaved(f);
    } catch (e) {
      onError((e as Error).message);
    }
  }
  return (
    <input value={v} onChange={(e) => setV(e.target.value)} onBlur={() => void save()}
           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
           size={4} placeholder="%" title="Marja, % (har qator uchun alohida)"
           style={{ textAlign: "right", borderColor: line.margin_pct === null || line.margin_pct === undefined ? "#e0a800" : undefined }} />
  );
}

/** O'z narxi bilan (custom) qator: narx ro'yxatida yo'q mahsulot narxi / tavsifi qo'lda yoziladi. */
function CustomFieldInput({ kp, line, field, onSaved, onError }:
  { kp: number; line: Line; field: "unit_price_excl_vat" | "description"; onSaved: () => void; onError: (m: string) => void }) {
  const initial = (field === "unit_price_excl_vat" ? line.unit_price_excl_vat : line.description) ?? "";
  const [v, setV] = useState(initial);
  useEffect(() => setV(initial), [initial]);
  async function save() {
    let s = v.trim();
    if (s === initial) return;
    if (field === "unit_price_excl_vat") {
      s = s.replace(/\s/g, "").replace(",", ".");
      if (!/^\d+(\.\d+)?$/.test(s)) { setV(initial); return onError("Narx — son bo'lishi kerak (masalan 125 yoki 99.50)"); }
    } else if (!s) { setV(initial); return onError("Tavsif bo'sh bo'lmasin"); }
    try {
      await api.patch(`/api/quotations/${kp}/lines/${line.line_id}`, { [field]: s });
      onSaved();
    } catch (e) {
      setV(initial);
      onError((e as Error).message);
    }
  }
  const missing = field === "unit_price_excl_vat" && (line.unit_price_excl_vat === null || line.unit_price_excl_vat === undefined);
  const props = {
    value: v, onBlur: () => void save(),
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); (e.target as HTMLElement).blur(); } },
  };
  return field === "description"
    ? <textarea {...props} onChange={(e) => setV(e.target.value)} rows={2} style={{ width: "100%" }}
                title="Tavsif (o'zgartirib Enter bosing)" />
    : <input {...props} onChange={(e) => setV(e.target.value)} size={8} placeholder="narx"
             title="Narx QQSsiz, USD (qo'lda yoziladi, Enter)"
             style={{ textAlign: "right", borderColor: missing ? "#d33" : undefined }} />;
}

function DiscountEditor({ kp, annex, evidence, onSaved, onError }:
  { kp: number; annex: Annex; evidence: Evidence[]; onSaved: () => void; onError: (m: string) => void }) {
  const [v, setV] = useState(fractionToPct(annex.discount_pct));
  const [reason, setReason] = useState(annex.discount_reason ?? "");
  async function save() {
    const f = pctToFraction(v);
    if (f === null || f === "0") return onError("Chegirma foizi — 0 dan katta son");
    try {
      await api.put(`/api/quotations/${kp}/annexes/${annex.annex_no}/discount`, { discount_pct: f, reason: reason || null });
      onSaved();
    } catch (e) {
      onError((e as Error).message);
    }
  }
  async function remove() {
    try {
      await api.del(`/api/quotations/${kp}/annexes/${annex.annex_no}/discount`);
      setV("");
      onSaved();
    } catch (e) {
      onError((e as Error).message);
    }
  }
  return (
    <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
      <label>Chegirma, % (QQS bilan jamidan)<input value={v} onChange={(e) => setV(e.target.value)} size={6} /></label>
      <label>Sabab<input value={reason} onChange={(e) => setReason(e.target.value)} size={30} /></label>
      <button className="secondary" onClick={() => void save()}>Chegirmani saqlash</button>
      {annex.discount_pct && <button className="danger" onClick={() => void remove()}>Olib tashlash</button>}
      {annex.discount_pct && (
        <EvidenceBox kp={kp} target={{ annex_id: annex.annex_id }} items={evidence} canUpload onChanged={onSaved} onError={onError} />
      )}
    </div>
  );
}

/** Chegirma isboti (2026-10-22): skrinshot (Ctrl+V yoki fayl) / PDF — chegirma o'zboshimcha emasligini isbotlash uchun.
 *  Fayl o'chirilmaydi va o'zgartirilmaydi; tasdiqlangan KP ga ham qo'shish mumkin (narxga ta'siri yo'q). */
function EvidenceBox({ kp, target, items, canUpload, onChanged, onError }:
  { kp: number; target: { line_id: number } | { annex_id: number }; items: Evidence[]; canUpload: boolean;
    onChanged: () => void; onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  async function upload(files: File[]) {
    if (!files.length) return;
    setBusy(true);
    try {
      for (const f of files) await api.post(`/api/quotations/${kp}/evidence` + qs(target), f);
      toast(files.length > 1 ? `${files.length} ta isbot yuklandi` : "Isbot yuklandi");
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="evidence">
      <b>Isbot (skrinshot / PDF)</b>{items.length === 0 && <span className="muted"> — hali yo'q</span>}
      <div className="evidence-list">
        {items.map((e) => {
          const url = `/api/quotations/${kp}/evidence/${e.id}/file`;
          return (
            <a key={e.id} href={url} target="_blank" rel="noreferrer" className="evidence-item"
               title={`${e.file_name} — ${e.uploaded_by_name}, ${dateUz(e.uploaded_at)}`}>
              {e.content_type.startsWith("image/") ? <img src={url} alt={e.file_name} /> : <span className="pdf">PDF</span>}
              <small>{e.file_name}</small>
            </a>
          );
        })}
      </div>
      {canUpload && (
        <div className="evidence-drop" tabIndex={0}
             onPaste={(e) => { const f = Array.from(e.clipboardData.files); if (f.length) { e.preventDefault(); void upload(f); } }}>
          {busy ? "Yuklanmoqda…" : "Skrinshotni shu yerga Ctrl+V bilan qo'ying yoki "}
          {!busy && (
            <label className="link">faylni tanlang
              <input type="file" hidden multiple accept="image/png,image/jpeg,image/webp,application/pdf"
                     onChange={(e) => { void upload(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
            </label>
          )}
          <span className="muted"> (PNG, JPEG, WEBP, PDF; 10 MB gacha)</span>
        </div>
      )}
    </div>
  );
}

/** Mahsulot (qator) chegirmasi (2026-10-22): faqat admin; foiz yoki summa (1 dona, QQS bilan narxdan); sabab majburiy;
 *  chegirmali narx butungacha yuqoriga yaxlitlanadi; ilova chegirmasi shu narxlardan keyin hisoblanadi. */
function LineDiscountEditor({ kp, line, cur, editable, canManage, evidence, onSaved, onError }:
  { kp: number; line: Line; cur: string; editable: boolean; canManage: boolean; evidence: Evidence[];
    onSaved: () => void; onError: (m: string) => void }) {
  const [kind, setKind] = useState<"pct" | "amount">(line.line_discount_kind ?? "pct");
  const [v, setV] = useState(line.line_discount_kind === "pct" ? fractionToPct(line.line_discount_value) : (line.line_discount_value ?? ""));
  const [reason, setReason] = useState(line.line_discount_reason ?? "");
  async function save() {
    const raw = v.trim().replace(/\s/g, "").replace(",", ".");
    const value = kind === "pct" ? pctToFraction(raw) : (/^\d+(\.\d+)?$/.test(raw) ? raw : null);
    if (value === null || Number(value) <= 0) return onError(kind === "pct" ? "Chegirma foizi — 0 dan katta son (masalan 5)" : "Chegirma summasi — 0 dan katta son");
    if (reason.trim().length < 3) return onError("Chegirma sababini yozing (kamida 3 belgi)");
    try {
      await api.put(`/api/quotations/${kp}/lines/${line.line_id}/discount`, { kind, value, reason: reason.trim() });
      toast("Mahsulot chegirmasi saqlandi");
      onSaved();
    } catch (e) {
      onError((e as Error).message);
    }
  }
  async function remove() {
    if (!window.confirm(`${line.line_no}-qator chegirmasi olib tashlansinmi?`)) return;
    try {
      await api.del(`/api/quotations/${kp}/lines/${line.line_id}/discount`);
      onSaved();
    } catch (e) {
      onError((e as Error).message);
    }
  }
  return (
    <div className="line-discount">
      {editable ? (
        <div className="row">
          <label>Chegirma turi
            <select value={kind} onChange={(e) => setKind(e.target.value as "pct" | "amount")}>
              <option value="pct">Foiz, %</option>
              <option value="amount">Summa, 1 dona uchun ({cur})</option>
            </select>
          </label>
          <label>{kind === "pct" ? "Foiz, % (QQS bilan narxdan)" : `Summa, ${cur} (QQS bilan)`}
            <input value={v} onChange={(e) => setV(e.target.value)} size={8} />
          </label>
          <label style={{ flex: 1 }}>Sabab (majburiy)
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Masalan: direktor ruxsati, mijoz bilan kelishuv…" />
          </label>
          <button className="secondary" onClick={() => void save()}>Saqlash</button>
          {line.line_discount_kind && <button className="danger" onClick={() => void remove()}>Olib tashlash</button>}
        </div>
      ) : line.line_discount_kind ? (
        <p style={{ margin: 0 }}>Chegirma: <b>{line.line_discount_kind === "pct" ? pct(line.line_discount_value) : `${money(line.line_discount_value, cur)} ${cur}`}</b>
          {" — "}{line.line_discount_reason}</p>
      ) : null}
      {line.line_discount_kind && (
        <EvidenceBox kp={kp} target={{ line_id: line.line_id }} items={evidence} canUpload={canManage} onChanged={onSaved} onError={onError} />
      )}
    </div>
  );
}

type Tool = "line" | "bulk" | "ahu" | "discount";

interface Found { model: string; description: string | null; price_excl_vat: string }

function AddLine({ kp, annexNo, onSaved, onError }: { kp: number; annexNo: number; onSaved: (w: string[]) => void; onError: (m: string) => void }) {
  const [mode, setMode] = useState<"price" | "custom">("price");
  const [model, setModel] = useState("");
  const [description, setDescription] = useState("");
  const [qty, setQty] = useState("1");
  const [unit, setUnit] = useState("шт");
  const [price, setPrice] = useState("");
  const [category, setCategory] = useState("");
  const [found, setFound] = useState<Found[]>([]);
  const [cats, setCats] = useState<{ name: string }[]>([]);
  const [units, setUnits] = useState<{ code: string }[]>([]);
  const [picker, setPicker] = useState(false);
  const [picked, setPicked] = useState("");
  useEffect(() => {
    api.get<{ name: string }[]>("/api/categories").then(setCats).catch(() => undefined);
    api.get<{ code: string }[]>("/api/units").then(setUnits).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (mode !== "price" || model.trim().length < 2) { setFound([]); return; }
    const t = setTimeout(() => {
      api.get<Found[]>("/api/price-list/search" + qs({ q: model.trim() })).then(setFound).catch(() => undefined);
    }, 250);
    return () => clearTimeout(t);
  }, [model, mode]);
  function reset() {
    setModel(""); setDescription(""); setQty("1"); setPrice(""); setPicked("");
  }
  async function add() {
    try {
      if (mode === "price") {
        const r = await api.post<{ warnings: string[]; merged: MergedLine | null }>(`/api/quotations/${kp}/annexes/${annexNo}/lines`,
          { model: model.trim(), quantity: qty, category: category || null });
        if (r.merged) toast(`${model.trim()} ilovada bor — ${r.merged.line_no}-qatorga qo'shildi (soni yig'ildi)`);
        reset();
        onSaved(r.warnings);
      } else {
        const r = await api.post<{ merged: MergedLine | null }>(`/api/quotations/${kp}/annexes/${annexNo}/custom-lines`, {
          description: description.trim(), model: model.trim() || null, category: category || null,
          quantity: qty, unit, price_excl_vat: price.replace(",", "."),
        });
        if (r.merged) toast(`${model.trim()} ilovada bor — ${r.merged.line_no}-qatorga qo'shildi (soni yig'ildi)`);
        reset();
        onSaved([]);
      }
    } catch (e) {
      onError((e as Error).message);
    }
  }
  const listId = `models-${annexNo}`;
  const canAdd = mode === "price" ? !!model.trim() : !!description.trim() && /^\d+([.,]\d+)?$/.test(price.trim());
  return (
    <div style={{ marginTop: 10 }}>
      <div className="row" style={{ marginBottom: 6 }}>
        <b>Mahsulot qo'shish:</b>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 4, color: "inherit" }}>
          <input type="radio" checked={mode === "price"} onChange={() => setMode("price")} /> narx ro'yxatidan
        </label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 4, color: "inherit" }}>
          <input type="radio" checked={mode === "custom"} onChange={() => setMode("custom")} /> o'z narxi bilan (ro'yxatda yo'q)
        </label>
      </div>
      <div className="row">
        {mode === "custom" && (
          <label>Наименование (tavsif)<input value={description} onChange={(e) => setDescription(e.target.value)} size={30} /></label>
        )}
        <label>{mode === "price" ? "Model (narx ro'yxatidan)" : "Model (ixtiyoriy)"}
          <input list={mode === "price" ? listId : undefined} value={model} onChange={(e) => { setModel(e.target.value); setPicked(""); }} size={20} />
          {mode === "price" && (
            <datalist id={listId}>
              {found.map((f) => <option key={f.model} value={f.model}>{`${f.description ?? ""} — ${money(f.price_excl_vat)} $`}</option>)}
            </datalist>
          )}
        </label>
        <label>Soni<input value={qty} onChange={(e) => setQty(e.target.value)} size={5} /></label>
        {mode === "custom" && (
          <>
            <label>Birlik
              <select value={unit} onChange={(e) => setUnit(e.target.value)}>
                {units.map((u) => <option key={u.code} value={u.code}>{u.code}</option>)}
              </select>
            </label>
            <label>Narx, USD (QQSsiz, marjagacha)<input value={price} onChange={(e) => setPrice(e.target.value)} size={10} /></label>
          </>
        )}
        <label>Kategoriya
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{mode === "price" ? "— avtomatik —" : "— tanlang —"}</option>
            {cats.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
        </label>
        {mode === "price" && (
          <button className={picker ? "secondary" : "accent"} onClick={() => setPicker((v) => !v)} title="Turi va kW bo'yicha qidirish">
            🔎 Katalogdan tanlash
          </button>
        )}
        <button disabled={!canAdd} onClick={() => void add()}>+ Qo'shish</button>
      </div>
      {mode === "price" && picked && <p className="muted" style={{ margin: "6px 0 0" }}>Tanlandi: <b>{model}</b> — {picked}. Sonini yozib "+ Qo'shish" ni bosing.</p>}
      {mode === "price" && picker && (
        <CatalogPicker onClose={() => setPicker(false)} onPick={(it) => {
          setModel(it.model);
          setPicked(`${it.type ?? ""}${it.capacity !== null ? `, ${Number(it.capacity)} ${it.capacity_unit ?? ""}` : ""}, ${money(it.price_incl_vat)} $ QQS bilan`);
          setPicker(false);
        }} />
      )}
      {mode === "custom" && (
        <p className="muted" style={{ margin: "4px 0 0" }}>
          Narxni siz kiritasiz (taxmin qilinmaydi). Marjani qo'shilgan qatorning "Маржа" katagiga yozing; QQS bilan narx = ROUNDUP(narx / (1 − marja) × 1.12).
        </p>
      )}
    </div>
  );
}

function QtyInput({ kp, line, onSaved, onError }: { kp: number; line: Line; onSaved: () => void; onError: (m: string) => void }) {
  const [v, setV] = useState(line.quantity);
  useEffect(() => setV(line.quantity), [line.quantity]);
  async function save() {
    const s = v.trim().replace(",", ".");
    if (s === line.quantity) return;
    if (!/^\d+(\.\d+)?$/.test(s) || Number(s) <= 0) { setV(line.quantity); return onError("Soni — musbat son bo'lishi kerak"); }
    try {
      await api.patch(`/api/quotations/${kp}/lines/${line.line_id}`, { quantity: s });
      onSaved();
    } catch (e) {
      setV(line.quantity);
      onError((e as Error).message);
    }
  }
  return (
    <input value={v} onChange={(e) => setV(e.target.value)} onBlur={() => void save()}
           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
           size={4} style={{ textAlign: "right" }} title="Soni (o'zgartirib Enter bosing)" />
  );
}

export default function QuotationDetail() {
  const { kp } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [revision, setRevision] = useState<number | undefined>();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<string[]>((location.state as { warnings?: string[] } | null)?.warnings ?? []);
  const [newAnnex, setNewAnnex] = useState("");
  const [newKind, setNewKind] = useState<"" | "empty" | "ahu">("");          // "Yangi ilova" menyusi (2026-10-20)
  // Har ilovaning amallar menyusi: bir vaqtda bitta oyna ochiq
  const [tool, setTool] = useState<{ annexNo: number; kind: Tool } | null>(null);
  const [lastBulk, setLastBulk] = useState<{ ids: number[]; merged: MergedLine[]; annexNo: number } | null>(null);   // ommaviy qo'shishni bekor qilish
  // 2026-10-16: amaliyotda bir KP dagi barcha AHU va valve qatorlariga bir xil marja — birinchisidan keyin qolganlariga taklif
  const [marginOffer, setMarginOffer] = useState<{ pct: string; ids: number[] } | null>(null);
  // Mahsulot chegirmasi oynasi ochiq qator va KP isbotlari (2026-10-22)
  const [discLine, setDiscLine] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const canSeeEvidence = can("discount.manage") || can("discount.report_all");

  const load = useCallback(() => {
    api.get<Detail>(`/api/quotations/${kp}` + qs({ revision_no: revision })).then(setD).catch((e) => setError(e.message));
  }, [kp, revision]);
  useEffect(load, [load]);
  const loadEvidence = useCallback(() => {
    if (canSeeEvidence) api.get<Evidence[]>(`/api/quotations/${kp}/evidence`).then(setEvidence).catch(() => setEvidence([]));
  }, [kp, canSeeEvidence]);
  useEffect(loadEvidence, [loadEvidence]);
  const reloadAll = () => { load(); loadEvidence(); };

  async function action(path: string, method: "post" | "del" = "post", after?: () => void) {
    setError("");
    try {
      await (method === "post" ? api.post(path) : api.del(path));
      if (after) after(); else load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!d) return error ? <div className="alert err">{error}</div>
    : <><div className="skeleton" style={{ height: 36, width: "55%" }} /><div className="skeleton row" /><div className="skeleton block" /></>;
  const cur = d.totals.display_currency;
  const kpNo = d.kp_number;
  const editable = d.totals.editable && can("kp.create_edit");
  const isLatest = d.revisions[d.revisions.length - 1].revision_no === d.totals.revision_no;
  const showBase = can("price.view") || editable;

  return (
    <>
      <div className="breadcrumb">
        <Link to="/">Bosh sahifa</Link> / <Link to="/kp">KP lar</Link> / <b>№ {d.kp_number}{d.totals.revision_no > 1 ? ` R${d.totals.revision_no}` : ""}</b>
      </div>
      <div className="title-bar">
        <h1>Коммерческое предложение № {d.kp_number}
          <button className="copy-btn" title="KP raqamini nusxalash" aria-label="KP raqamini nusxalash" onClick={() => {
            void copyText(String(d.kp_number)).then((ok) => (ok ? toast(`№ ${d.kp_number} nusxalandi`) : toast("Nusxalab bo'lmadi", "err")));
          }}>⧉</button>
        </h1>
        <ol className="statusbar" aria-label="KP holati">
          {(["draft", "approved", "sent"] as const).map((st, i, all) => {
            const cur = all.indexOf(d.totals.status as (typeof all)[number]);
            return <li key={st} className={i === cur ? "on" : i < cur ? "done" : ""}>{STATUS_UZ[st]}</li>;
          })}
        </ol>
      </div>
      {editable && (() => {
        const lines = d.annexes.flatMap((a) => a.lines);
        const ahu = lines.filter((l) => l.line_type === "ahu");
        const steps = [
          { t: "Mahsulotlar qo'shildi", ok: lines.length > 0 },
          { t: "Marja kiritildi", ok: ahu.every((l) => l.margin_pct !== null && l.margin_pct !== undefined), na: ahu.length === 0 },
          { t: "Narxlar to'liq", ok: lines.length > 0 && Number(d.totals.missing_price_lines) === 0 },
          { t: "Tasdiqlash", ok: false },
          { t: "Yuborish va Excel", ok: false },
        ];
        const next = steps.findIndex((s) => !s.ok && !s.na);
        return (
          <ol className="progress">
            {steps.map((s, i) => (
              <li key={s.t} className={s.ok || s.na ? "done" : i === next ? "on" : ""}>
                <span className="dot">{s.ok || s.na ? "✓" : i + 1}</span>
                <span>{s.t}{s.na ? " (kerak emas)" : ""}</span>
              </li>
            ))}
          </ol>
        );
      })()}
      <div className="panel">
        <dl className="kv">
          <dt>Loyiha</dt><dd>{d.project_name} <span className="muted">#{d.project_no}</span></dd>
          <dt>Menejer</dt><dd>{d.manager_name}{d.manager_phone ? ` — ${d.manager_phone}` : ""}</dd>
          <dt>Sana</dt><dd>{dateUz(d.totals.kp_date)} <span className="muted">(amal qiladi: {dateUz(d.totals.valid_until)} gacha)</span></dd>
          <dt>Revision</dt>
          <dd className="row">
            <select value={d.totals.revision_no} onChange={(e) => setRevision(Number(e.target.value))}>
              {d.revisions.map((r) => (
                <option key={r.revision_no} value={r.revision_no}>
                  {r.revision_no} — {dateUz(r.kp_date)} ({STATUS_UZ[r.status] ?? r.status})
                </option>
              ))}
            </select>
            <span className={`badge ${d.totals.status === "sent" ? "ok" : ""}`}>{STATUS_UZ[d.totals.status] ?? d.totals.status}</span>
          </dd>
          <dt>Valyuta</dt>
          <dd className="row">
            <span>{cur}{d.exchange_rate && <span className="muted"> — kurs {d.exchange_rate.rate} ({dateUz(d.exchange_rate.rate_date)})</span>}</span>
            {d.totals.status !== "cancelled" && (d.totals.status === "draft" ? editable : can("kp.approve")) && (
              <CurrencyEditor key={`${d.totals.revision_no}-${cur}-${d.exchange_rate?.id ?? ""}`} kp={kpNo} revisionNo={d.totals.revision_no}
                              cur={cur} rateId={d.exchange_rate?.id ?? null} ready={d.totals.status !== "draft"} onSaved={load} />
            )}
          </dd>
          {d.currency_changes.length > 0 && (
            <>
              <dt>Valyuta tarixi</dt>
              <dd>
                {d.currency_changes.map((c) => (
                  <div key={c.changed_at} className="muted">
                    {dateUz(c.changed_at.slice(0, 10))} {c.changed_at.slice(11, 16)} — {c.changed_by_name}:{" "}
                    {c.old_currency}{c.old_rate ? ` (${c.old_rate})` : ""} → {c.new_currency}{c.new_rate ? ` (${c.new_rate})` : ""}
                    {" "}({STATUS_UZ[c.status_at_change] ?? c.status_at_change} holatida)
                  </div>
                ))}
              </dd>
            </>
          )}
        </dl>
      </div>
      <div className="sum-cards">
        <div className="sum-card"><span>Ilovalar</span><b>{d.annexes.length}</b>
          <small>{d.annexes.reduce((n, a) => n + a.lines.length, 0)} ta qator</small></div>
        {Number(d.totals.discount_amount) > 0 && (
          <>
            <div className="sum-card"><span>Chegirmasiz</span><b title={d.totals.subtotal ?? ""}>{money(d.totals.subtotal, cur)} <small className="cur">{cur}</small></b></div>
            <div className="sum-card disc"><span>Chegirma</span><b title={d.totals.discount_amount ?? ""}>−{money(d.totals.discount_amount, cur)} <small className="cur">{cur}</small></b></div>
          </>
        )}
        <div className="sum-card main"><span>Jami (QQS bilan)</span>
          {Number(d.totals.missing_price_lines) > 0
            ? <b className="err-text">narx yo'q: {d.totals.missing_price_lines} qator</b>
            : <b title={d.totals.total_incl_vat ?? ""}>{money(d.totals.total_incl_vat, cur)} <small className="cur">{cur}</small></b>}
          <small>shundan QQS {money(d.totals.vat_amount_info, cur)}</small></div>
      </div>
      {DEAL_TRACKING && <DealPanel kp={kpNo} />}
      <div className="row" style={{ marginBottom: 12 }}>
        {can("kp.download") && <ExcelButton kp={kpNo} revisionNo={d.totals.revision_no} annexCount={d.annexes.length}
                                                 hasLineDiscount={d.annexes.some((a) => a.lines.some((l) => l.line_discount_kind))} />}
        {editable && can("kp.approve") && <button onClick={() => void action(`/api/quotations/${kpNo}/approve`)}>Tasdiqlash</button>}
        {isLatest && d.totals.status === "approved" && can("kp.approve") && (
          <button onClick={() => void action(`/api/quotations/${kpNo}/send`)}>Yuborildi deb belgilash</button>
        )}
        {isLatest && d.totals.status !== "draft" && can("kp.create_edit") && (
          <button className="secondary" onClick={() => void action(`/api/quotations/${kpNo}/revisions`, "post", () => { setRevision(undefined); load(); })}>
            Yangi revision (o'zgartirish uchun)
          </button>
        )}
      </div>
      {error && <div className="alert err">{error}</div>}
      {notes.map((n) => <div className="alert warn" key={n}>{n}</div>)}
      {editable && marginOffer && (
        <div className="prompt floating">
          <span style={{ fontSize: 20 }}>％</span>
          <span className="q">
            <b>Qolgan {marginOffer.ids.length} ta AHU/valve qatoriga ham {fractionToPct(marginOffer.pct)} % marja qo'yilsinmi?</b>
            <br /><span className="muted">Har qatorda o'z katagi qoladi — keyin istalganini alohida o'zgartirish mumkin.</span>
          </span>
          <button className="accent" onClick={() => {
            const o = marginOffer;
            setMarginOffer(null);
            void Promise.all(o.ids.map((id) => api.patch(`/api/quotations/${kpNo}/lines/${id}`, { margin_pct: o.pct })))
              .then(() => load()).catch((e) => { setError((e as Error).message); load(); });
          }}>Ha, qo'yish</button>
          <button className="secondary" onClick={() => setMarginOffer(null)}>Yo'q</button>
        </div>
      )}
      {editable && d.annexes.some((a) => a.lines.some((l) => l.line_type === "ahu")) && (   // faqat AHU fayldan tuzilgan KP
        <div className="alert warn">
          Qoralama: marjani har bir AHU/valve qatori uchun alohida kiriting (%, Enter yoki boshqa joyni bosing — saqlanadi).
          VRF/kit va narx ro'yxati modellariga marja qo'shilmaydi. Tasdiqlangach KP o'zgarmaydi — faqat yangi revision orqali.
        </div>
      )}
      {Number(d.totals.missing_price_lines) > 0 && (
        <div className="alert warn">Bu KP da narxi noma'lum {d.totals.missing_price_lines} ta qator bor — jami summa hisoblanmaydi (TEKSHIRISH KERAK).</div>
      )}

      {d.annexes.map((a) => (
        <div className="panel table-wrap" key={a.annex_id}>
          <div className="annex-head">
            <h2 style={{ margin: 0 }}>Приложение № {a.annex_no} — {a.name}</h2>
            {editable && (
              <span className="row" style={{ gap: 6 }}>
                <button className="secondary small" title="Ilova nomini o'zgartirish" onClick={() => {
                  const nm = window.prompt(`${a.annex_no}-ilova nomi:`, a.name)?.trim();
                  if (nm && nm !== a.name) void api.patch(`/api/quotations/${kpNo}/annexes/${a.annex_no}`, { name: nm }).then(load).catch((e) => setError(e.message));
                }}>✎ Nomi</button>
                {d.annexes.length > 1 && (
                  <button className="danger small" title="Ilovani qatorlari bilan o'chirish" onClick={() => {
                    if (!window.confirm(`${a.annex_no}-ilova "${a.name}" (${a.lines.length} ta qator) o'chirilsinmi? Keyingi ilovalar raqami bittaga suriladi.`)) return;
                    setTool(null);
                    void api.del(`/api/quotations/${kpNo}/annexes/${a.annex_no}`).then(() => { toast("Ilova o'chirildi"); load(); }).catch((e) => setError(e.message));
                  }}>🗑 O'chirish</button>
                )}
              </span>
            )}
          </div>
          <table>
            <thead>
              <tr>
                <th>№</th><th>Категория</th><th>Описание</th><th>Модель</th><th className="num">Производ.</th>
                <th className="num">Кол-во</th><th>Ед.</th>
                {showBase && <th className="num">Цена без НДС (USD)</th>}
                {showBase && <th className="num">Маржа</th>}
                <th className="num">Цена за ед. с НДС</th><th className="num">Сумма с НДС</th>
                {editable && <th></th>}
              </tr>
            </thead>
            <tbody>
              {a.lines.map((l) => (
                <Fragment key={l.line_no}>
                <tr>
                  <td>{l.line_no}</td>
                  <td>{l.category ?? <span className="badge warn">yo'q</span>}</td>
                  <td className="desc">
                    {editable && l.line_type === "custom"
                      ? <CustomFieldInput kp={kpNo} line={l} field="description" onSaved={load} onError={setError} />
                      : (l.description ?? "—")}
                  </td>
                  <td className="model">{l.model ?? "—"}</td>
                  <td className="num">{l.performance ? `${l.performance} ${l.performance_unit ?? ""}` : ""}</td>
                  <td className="num">
                    {editable ? <QtyInput kp={kpNo} line={l} onSaved={load} onError={setError} /> : l.quantity}
                  </td>
                  <td>{l.unit_code ?? "—"}</td>
                  {showBase && (
                    <td className="num" title={l.unit_price_excl_vat ?? ""}>
                      {editable && l.line_type === "custom"
                        ? <CustomFieldInput kp={kpNo} line={l} field="unit_price_excl_vat" onSaved={load} onError={setError} />
                        : money(l.unit_price_excl_vat)}
                    </td>
                  )}
                  {showBase && (
                    <td className="num">
                      {editable && l.line_type !== "price_list"
                        ? <MarginInput kp={kpNo} line={l} onError={setError} onSaved={(f) => {
                            const rest = d.annexes.flatMap((x) => x.lines)
                              .filter((x) => x.line_type === "ahu" && x.line_id !== l.line_id && (x.margin_pct === null || x.margin_pct === undefined))
                              .map((x) => x.line_id);
                            setMarginOffer(f !== undefined && rest.length ? { pct: f, ids: rest } : null);
                            load();
                          }} />
                        : (l.margin_pct ? pct(l.margin_pct) : "")}
                    </td>
                  )}
                  <td className="num" title={l.display_unit_net ?? ""}>
                    {l.line_discount_kind && <><s className="muted" title={l.display_unit_price ?? ""}>{money(l.display_unit_price, cur)}</s><br /></>}
                    {money(l.display_unit_net, cur)}
                    {(l.line_discount_kind ? canSeeEvidence : editable && can("discount.manage")) && l.display_unit_price !== null && (
                      <button className={"disc-chip" + (l.line_discount_kind ? " on" : "")}
                              title={l.line_discount_kind ? `Chegirma: ${l.line_discount_reason ?? ""}${l.evidence_count ? ` (isbot: ${l.evidence_count})` : ""}` : "Mahsulotga chegirma berish"}
                              onClick={() => setDiscLine(discLine === l.line_id ? null : l.line_id)}>
                        {l.line_discount_kind
                          ? `−${l.line_discount_kind === "pct" ? pct(l.line_discount_value) : money(l.line_discount_value, cur)}${l.evidence_count ? " 📎" : ""}`
                          : "％"}
                      </button>
                    )}
                    {l.line_discount_kind && !canSeeEvidence && <span className="disc-chip on" title="Mahsulot chegirmasi">−</span>}
                  </td>
                  <td className="num" title={l.display_line_net ?? ""}>
                    {l.display_line_total === null ? <span className="badge err">narx yo'q</span> : money(l.display_line_net, cur)}
                  </td>
                  {editable && (
                    <td><button className="danger" title="Qatorni o'chirish"
                                onClick={() => { if (window.confirm(`${l.line_no}-qator o'chirilsinmi?`)) void action(`/api/quotations/${kpNo}/lines/${l.line_id}`, "del"); }}>×</button></td>
                  )}
                </tr>
                {discLine === l.line_id && (
                  <tr className="line-discount-row">
                    <td colSpan={(showBase ? 11 : 9) + (editable ? 1 : 0)}>
                      <LineDiscountEditor kp={kpNo} line={l} cur={cur} editable={editable && can("discount.manage")} canManage={can("discount.manage")}
                                          evidence={evidence.filter((e) => e.line_ids.includes(l.line_id))}
                                          onSaved={reloadAll} onError={setError} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
              <tr className="total">
                <td colSpan={5}>Итого {cur}</td>
                <td className="num">{a.total_quantity}</td>
                <td colSpan={(showBase ? 4 : 2) + (editable ? 1 : 0)}></td>
                <td className="num" title={a.subtotal ?? ""}>
                  {a.subtotal === null ? <span className="badge err">noma'lum</span> : money(a.subtotal, cur)}
                </td>
              </tr>
              {Number(a.line_discount_amount) > 0 && (
                <tr className="discount">
                  <td colSpan={showBase ? 10 : 8}>Скидка на отдельные позиции</td>
                  <td className="num" title={a.line_discount_amount ?? ""}>−{money(a.line_discount_amount, cur)}</td>
                </tr>
              )}
              {a.discount_pct && (
                <tr className="discount">
                  <td colSpan={showBase ? 10 : 8}>Скидка {pct(a.discount_pct)}{a.discount_reason ? ` — ${a.discount_reason}` : ""}
                    {a.evidence_count > 0 && <span title="Isbot biriktirilgan"> 📎</span>}</td>
                  <td className="num" title={a.discount_amount ?? ""}>−{money(a.discount_amount, cur)}</td>
                </tr>
              )}
              {(a.discount_pct || Number(a.line_discount_amount) > 0) && (
                <>
                  <tr className="grand">
                    <td colSpan={showBase ? 10 : 8}>Итого со скидкой, {cur}</td>
                    <td className="num" title={a.total_after_discount ?? ""}>{money(a.total_after_discount, cur)}</td>
                  </tr>
                </>
              )}
            </tbody>
          </table>
          {editable && (
            <AccessoryPrompt kp={kpNo} revisionNo={d.totals.revision_no} annexNo={a.annex_no}
                             version={a.lines.map((l) => `${l.line_id}:${l.quantity}`).join(",")}
                             onAdded={(added) => { setNotes(added.length ? ["Qo'shildi: " + added.join(", ")] : []); load(); }} onError={setError} />
          )}
          {editable && (() => {
            const on = (k: Tool) => tool?.annexNo === a.annex_no && tool.kind === k;
            const close = () => setTool(null);
            const items: [Tool, string][] = [["line", "＋ Model qo'shish"], ["bulk", "📋 Ro'yxatdan (Excel)"]];
            if (can("ahu.import")) items.push(["ahu", "🌀 AHU faylidan"]);
            if (can("discount.manage")) items.push(["discount", "％ Chegirma"]);
            return (
              <>
                <div className="annex-menu" role="toolbar" aria-label={`${a.annex_no}-ilovaga qo'shish`}>
                  {items.map(([k, t]) => (
                    <button key={k} className={on(k) ? "" : "secondary"} aria-pressed={on(k)}
                            onClick={() => setTool(on(k) ? null : { annexNo: a.annex_no, kind: k })}>{t}</button>
                  ))}
                  {lastBulk && lastBulk.annexNo === a.annex_no && (
                    <button className="secondary" title="Oxirgi ro'yxat bilan qo'shilgan qatorlarni olib tashlash"
                            onClick={() => {
                              const n = lastBulk.ids.length + lastBulk.merged.length;
                              if (!window.confirm(`Oxirgi ro'yxat bekor qilinsinmi? ${lastBulk.ids.length} ta yangi qator olib tashlanadi` +
                                (lastBulk.merged.length ? `, ${lastBulk.merged.length} ta qatorning soni oldingi holatiga qaytadi` : "") + ` (jami ${n}).`)) return;
                              // avval yig'ilgan qatorlarning sonini qaytarish, keyin yangi qatorlarni o'chirish
                              const steps = [
                                ...lastBulk.merged.map((m) => () => api.patch(`/api/quotations/${kpNo}/lines/${m.line_id}`, { quantity: m.old_quantity })),
                                ...lastBulk.ids.map((id) => () => api.del(`/api/quotations/${kpNo}/lines/${id}`)),
                              ];
                              void steps.reduce<Promise<unknown>>((p, step) => p.then(step), Promise.resolve())
                                .then(() => { toast("Oxirgi ro'yxat bekor qilindi"); setLastBulk(null); load(); })
                                .catch((e) => { setError((e as Error).message); load(); });
                            }}>↶ Bekor qilish ({lastBulk.ids.length + lastBulk.merged.length} ta)</button>
                  )}
                </div>
                {a.lines.length === 0 && !tool && <p className="muted" style={{ margin: "6px 0 0" }}>Ilova bo'sh — yuqoridagi tugmalardan birini tanlang.</p>}
                {on("line") && <AddLine kp={kpNo} annexNo={a.annex_no} onSaved={(w) => { setNotes(w); load(); }} onError={setError} />}
                {on("bulk") && <BulkAdd kp={kpNo} annexNo={a.annex_no} onError={setError} onClose={close} onDone={(ids, w, merged) => {
                  setNotes(w); load();
                  setLastBulk({ ids, merged, annexNo: a.annex_no });
                }} />}
                {on("ahu") && <AhuUpload kp={kpNo} annexNo={a.annex_no} projectName={d.project_name} onClose={close} onError={setError}
                                         onDone={(w) => { setNotes(w); close(); load(); }} />}
                {on("discount") && <DiscountEditor kp={kpNo} annex={a} evidence={evidence.filter((e) => e.annex_ids.includes(a.annex_id))}
                                                  onSaved={reloadAll} onError={setError} />}
              </>
            );
          })()}
        </div>
      ))}
      {editable && (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>➕ Yangi ilova qo'shish</h2>
          <div className="choice-grid">
            <button className={"choice" + (newKind === "empty" ? " on" : "")} onClick={() => setNewKind(newKind === "empty" ? "" : "empty")}>
              <span className="choice-icon">📦</span><b>Bo'sh ilova</b>
              <span className="muted">VRF, 2-этаж va h.k. — keyin katalogdan yoki Excel ro'yxatdan to'ldirasiz</span>
            </button>
            <button className={"choice" + (newKind === "ahu" ? " on" : "")} disabled={!can("ahu.import")}
                    onClick={() => setNewKind(newKind === "ahu" ? "" : "ahu")}>
              <span className="choice-icon">🌀</span><b>AHU faylidan</b>
              <span className="muted">Zavod quotation.xlsx — AHU, automation, VRF, kit va valve avtomatik</span>
            </button>
          </div>
          {newKind === "empty" && (
            <div className="row" style={{ marginTop: 12 }}>
              <label>Ilova nomi<input value={newAnnex} onChange={(e) => setNewAnnex(e.target.value)} placeholder="masalan VRF yoki 2-этаж" autoFocus /></label>
              <button className="accent" disabled={!newAnnex.trim()}
                      onClick={() => void api.post<{ annex_no: number }>(`/api/quotations/${kpNo}/annexes`, { name: newAnnex.trim() })
                        .then((r) => { setNewAnnex(""); setNewKind(""); setTool({ annexNo: r.annex_no, kind: "line" }); load(); })
                        .catch((e) => setError(e.message))}>
                ✓ Ilova yaratish
              </button>
            </div>
          )}
          {newKind === "ahu" && (
            <AhuUpload kp={kpNo} projectName={d.project_name} onClose={() => setNewKind("")} onError={setError}
                       onDone={(w) => { setNotes(w); setNewKind(""); load(); }} />
          )}
        </div>
      )}

      <div className="panel">
        <table>
          <tbody>
            {d.annexes.length > 1 && (
              <tr className="grand">
                <td>Общая стоимость, {cur}</td>
                <td className="num" title={d.totals.total_incl_vat ?? ""}>{money(d.totals.total_incl_vat, cur)}</td>
              </tr>
            )}
            {d.annexes.length === 1 && (
              <tr className="grand">
                <td>Jami, {cur} (QQS bilan)</td>
                <td className="num" title={d.totals.total_incl_vat ?? ""}>{money(d.totals.total_incl_vat, cur)}</td>
              </tr>
            )}
            <tr>
              <td className="muted">в т.ч. НДС 12% (ma'lumot uchun)</td>
              <td className="num muted">{money(d.totals.vat_amount_info, cur)}</td>
            </tr>
            <tr>
              <td className="muted">Сумма без НДС (ma'lumot uchun)</td>
              <td className="num muted">{money(d.totals.total_excl_vat_info, cur)}</td>
            </tr>
          </tbody>
        </table>
        <p className="muted" style={{ marginBottom: 0 }}>Summalar ko'rsatish uchun yaxlitlangan; aniq qiymat — sichqonchani summa ustiga olib boring.</p>
      </div>
      {can("kp.delete") && (
        <details className="panel danger-zone">
          <summary>⚠ Xavfli amallar</summary>
          <p className="muted">KP o'chirilsa, barcha revisionlari bilan yo'qoladi (o'zgarishlar jurnalida qoladi, raqam bo'sh qoladi).</p>
          <button className="danger" onClick={() => {
            const allDraft = d.revisions.every((r) => r.status === "draft");
            const ok = allDraft
              ? window.confirm(`KP ${kpNo} (qoralama) butunlay o'chirilsinmi?`)
              : window.prompt(`DIQQAT: KP ${kpNo} tasdiqlangan/yuborilgan. U barcha ${d.revisions.length} ta revisioni bilan BUTUNLAY o'chiriladi `
                  + `(jurnalda qoladi, raqam bo'sh qoladi).\nTasdiqlash uchun KP raqamini yozing:`) === String(kpNo);
            if (ok) void action(`/api/quotations/${kpNo}`, "del", () => navigate("/kp"));
          }}>
            KP ni o'chirish
          </button>
        </details>
      )}
    </>
  );
}
