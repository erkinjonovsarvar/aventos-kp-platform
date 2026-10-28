// Qalqib chiquvchi xabarlar (o'ng pastda, o'zi yo'qoladi) — sahifa siljimaydi (UX audit 2026-10-17, 17-band).
type Kind = "ok" | "err" | "warn";

function host(): HTMLElement {
  let el = document.getElementById("toasts");
  if (!el) {
    el = document.createElement("div");
    el.id = "toasts";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
  }
  return el;
}

export function toast(message: string, kind: Kind = "ok", ms = kind === "err" ? 7000 : 3500): void {
  if (!message) return;
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = (kind === "ok" ? "✓ " : kind === "err" ? "⚠ " : "") + message;
  const close = () => { t.classList.add("out"); window.setTimeout(() => t.remove(), 250); };
  t.addEventListener("click", close);
  host().appendChild(t);
  window.setTimeout(close, ms);
}

/** Matnni nusxalash: zamonaviy usul, ishlamasa — eski (textarea) usul. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}
