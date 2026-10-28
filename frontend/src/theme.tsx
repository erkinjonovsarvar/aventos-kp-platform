import { useEffect, useState } from "react";

type Theme = "light" | "dark";
const KEY = "aventos.theme";

function initial(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* brauzer xotirasi yopiq */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Kun / tun rejimi: tanlov shu brauzerda eslab qolinadi; tanlanmagan bo'lsa — kompyuter sozlamasi. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(KEY, theme); } catch { /* faqat shu sahifa uchun */ }
  }, [theme]);
  const dark = theme === "dark";
  return (
    <button type="button" className="theme-toggle" onClick={() => setTheme(dark ? "light" : "dark")}
            title={dark ? "Kunduzgi rejim" : "Tungi rejim (ko'zni charchatmaydi)"} aria-label={dark ? "Kunduzgi rejim" : "Tungi rejim"}>
      {dark ? "☀️" : "🌙"}
    </button>
  );
}

/** Logo: tun rejimida och rangli varianti. */
export function Logo({ className, height }: { className?: string; height?: number }) {
  return (
    <>
      <img className={`${className ?? ""} logo-light`} src="/logo.png" alt="AVENTOS air design" style={height ? { height } : undefined} />
      <img className={`${className ?? ""} logo-dark`} src="/logo-dark.png" alt="AVENTOS air design" style={height ? { height } : undefined} />
    </>
  );
}
