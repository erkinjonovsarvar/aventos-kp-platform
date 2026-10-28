import { useEffect, useState } from "react";
import { api } from "../api";

export interface Catalog {
  permissions: { code: string; name: string }[];
  roles: { code: string; name: string; permissions: string[] }[];
}

let cache: Promise<Catalog> | null = null;
export function useCatalog(): Catalog | null {
  const [c, setC] = useState<Catalog | null>(null);
  useEffect(() => {
    cache ??= api.get<Catalog>("/api/admin/permissions");
    cache.then(setC).catch(() => { cache = null; });
  }, []);
  return c;
}

/** Rol (shablon) + alohida ruxsatlar. Shablondan keladigan ruxsatlar belgilangan va o'chirilgan holda ko'rsatiladi. */
export default function PermissionPicker({
  roles, extra, onChange,
}: {
  roles: string[];
  extra: string[];
  onChange: (roles: string[], extra: string[]) => void;
}) {
  const catalog = useCatalog();
  if (!catalog) return <div className="skeleton block" style={{ height: 120 }} />;
  const fromRoles = new Set(catalog.roles.filter((r) => roles.includes(r.code)).flatMap((r) => r.permissions));
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <b>Rol (shablon):</b>
        {catalog.roles.map((r) => (
          <label key={r.code} style={{ flexDirection: "row", alignItems: "center", gap: 4, color: "inherit" }}>
            <input type="checkbox" checked={roles.includes(r.code)} onChange={() => onChange(toggle(roles, r.code), extra)} />
            {r.name}
          </label>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 4 }}>
        {catalog.permissions.map((p) => {
          const viaRole = fromRoles.has(p.code);
          const adminOnly = p.code === "kp.delete";          // faqat admin rolida, alohida berilmaydi
          return (
            <label key={p.code} style={{ flexDirection: "row", alignItems: "center", gap: 6, color: "inherit" }}
                   title={viaRole ? "Roldan keladi" : "Alohida ruxsat"}>
              <input type="checkbox" disabled={viaRole || adminOnly} checked={viaRole || extra.includes(p.code)}
                     onChange={() => onChange(roles, toggle(extra, p.code))} />
              <span>{p.name} {viaRole ? <span className="muted">(roldan)</span> : adminOnly && <span className="muted">(faqat admin)</span>}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
