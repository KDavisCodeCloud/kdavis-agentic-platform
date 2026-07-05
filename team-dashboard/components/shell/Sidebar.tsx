"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS } from "@/lib/types";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="shrink-0 flex flex-col h-screen pt-5 pb-4"
      style={{
        width: "196px",
        backgroundColor: "#0f1520",
        borderRight: "1px solid #1c2535",
      }}
    >
      {/* Wordmark */}
      <div className="px-4 mb-5">
        <p className="text-[14px] font-bold leading-none" style={{ color: "#eef2f5" }}>
          THD STACK
        </p>
        <p className="text-[10px] font-mono mt-0.5" style={{ color: "#5b6673" }}>
          builder · team member
        </p>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-0.5 px-2">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || (pathname === "/" && item.href === "/tasks");
          return (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-2 px-2.5 py-[9px] rounded-[8px] text-[12.5px] transition-colors"
              style={{
                backgroundColor: active ? "#5eead41a" : "transparent",
                color: active ? "#5eead4" : "#8b96a3",
                fontWeight: active ? 600 : 400,
              }}
            >
              {/* 12×12 square outline icon placeholder */}
              <span
                className="shrink-0"
                style={{
                  width: "12px",
                  height: "12px",
                  border: `1.5px solid ${active ? "#5eead4" : "#5b6673"}`,
                  borderRadius: "2px",
                  display: "inline-block",
                }}
              />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
