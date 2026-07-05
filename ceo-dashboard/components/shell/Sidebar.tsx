"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DEPT_ROUTES, type Role } from "@/lib/types";

export function Sidebar({ role }: { role: Role }) {
  const pathname = usePathname();

  const visible = DEPT_ROUTES.filter((d) => (d.roles as readonly string[]).includes(role));

  return (
    <nav
      className="flex flex-col py-4 shrink-0"
      style={{
        width: "196px",
        backgroundColor: "#0e1218",
        borderRight: "1px solid #1c222b",
        height: "100vh",
      }}
    >
      {/* Wordmark */}
      <div className="px-3 mb-5">
        <p className="text-[14px] font-bold tracking-wide" style={{ color: "#eef2f5" }}>
          CEO DECODED
        </p>
        <p className="text-[10px] font-mono" style={{ color: "#5b6673" }}>
          THD Agentic Systems LLC
        </p>
      </div>

      {/* Nav items */}
      <ul className="flex flex-col gap-0.5 px-2">
        {visible.map((dept) => {
          const active = pathname.startsWith(dept.path);
          return (
            <li key={dept.id}>
              <Link
                href={dept.path}
                className="flex items-center gap-2 rounded-[8px] transition-colors"
                style={{
                  padding: "9px 10px",
                  backgroundColor: active ? "#5eead41a" : "transparent",
                  color: active ? "#5eead4" : "#8b96a3",
                  fontWeight: active ? 600 : 400,
                  fontSize: "12.5px",
                  textDecoration: "none",
                }}
              >
                {/* Placeholder square icon */}
                <span
                  className="shrink-0"
                  style={{
                    width: 12,
                    height: 12,
                    border: `1.5px solid ${active ? "#5eead4" : "#5b6673"}`,
                    borderRadius: "2px",
                    display: "inline-block",
                  }}
                />
                <span className="truncate-text">{dept.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
