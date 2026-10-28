// Backend API bilan ishlash. Sessiya HttpOnly cookie'da — JavaScript uni ko'rmaydi.

export class ApiError extends Error {
  constructor(public status: number, message: string, public data?: unknown) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let payload: BodyInit | undefined;
  let headers: Record<string, string> | undefined;
  if (body instanceof File) {
    payload = new FormData();
    payload.append("file", body);
  } else if (body !== undefined) {
    payload = JSON.stringify(body);
    headers = { "Content-Type": "application/json" };
  }
  const res = await fetch(path, { method, credentials: "same-origin", headers, body: payload });
  if (!res.ok) {
    let message = `Xato ${res.status}`;
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      if (typeof data.detail === "string") message = data.detail;
      else if (data.detail && typeof data.detail.message === "string") message = data.detail.message;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* javob JSON emas */
    }
    // admin paneli maxfiy so'zi muddati tugagan — interfeys darvozani qayta ko'rsatadi
    if (res.status === 403 && typeof (detail as { code?: string } | undefined)?.code === "string"
        && (detail as { code: string }).code.startsWith("admin_word")) window.dispatchEvent(new Event("admin-locked"));
    throw new ApiError(res.status, message, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, file: File) => request<T>("POST", path, file),
};

/** Foizni (masalan "12.5") kasrga ("0.125") MATN orqali aylantirish — float xatosiz. */
export function pctToFraction(input: string): string | null {
  const s = input.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const [int, frac = ""] = s.split(".");
  const digits = (int.padStart(3, "0") + frac).replace(/^0+(?=\d)/, "");
  const pointAt = digits.length - frac.length - 2;
  const whole = pointAt > 0 ? digits.slice(0, pointAt) : "0";
  const rest = (pointAt > 0 ? digits.slice(pointAt) : "0".repeat(-pointAt) + digits).replace(/0+$/, "");
  return rest ? `${whole}.${rest}` : whole;
}

/** Kasrni ("0.125") foizga ("12.5") — ko'rsatish uchun. */
export function fractionToPct(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const [int, frac = ""] = value.split(".");
  const f = frac.padEnd(2, "0");
  const whole = String(Number(int + f.slice(0, 2)));
  const rest = f.slice(2).replace(/0+$/, "");
  return rest ? `${whole}.${rest}` : whole;
}

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

// ---- turlar
export type Money = string | null; // pul summalari backend'dan MATN bo'lib keladi (aniqlik yo'qolmasligi uchun)

export interface User {
  id: number;
  login: string;
  full_name: string;
  employee_id: number;
  access_valid_until: string | null;
  roles: string[];
  permissions: string[];
  mfa_enabled?: boolean;
  mfa_setup_required?: boolean;
  admin_word_set?: boolean;
  telegram_name?: string | null;
  admin_unlocked?: boolean;
}

export interface QuotationRow {
  kp_number: number;
  project_no: number;
  project_name: string;
  manager_id: number;
  manager_name: string;
  revision_no: number;
  kp_date: string;
  valid_until: string;
  status: string;
  display_currency: string;
  deal_status?: string | null;
  deal_status_name?: string | null;
  annex_count: number;
  subtotal: Money;
  discount_amount: Money;
  total_incl_vat: Money;
  missing_price_lines: string;
}

// ---- formatlash (faqat ko'rsatish; asl qiymat o'zgarmaydi — sichqoncha ustida to'liq qiymat)
export function money(value: Money | undefined, currency?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  const digits = currency === "UZS" ? 0 : 2;
  return n.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).replace(/,/g, ".");
}

export function pct(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value) * 100;
  return `${Number.isInteger(n) ? n : n.toFixed(2)} %`;
}

export function dateUz(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

export const STATUS_UZ: Record<string, string> = {
  draft: "Qoralama",
  approved: "Tasdiqlangan",
  sent: "Yuborilgan",
  cancelled: "Bekor qilingan",
};
