"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { DEPT_ROUTES, type Role } from "@/lib/types";

// Confirmed 2026-07-27: the desktop shell (IconRail 60px + Sidebar 196px,
// both fixed-width, zero responsive classes) ate 60-68% of a phone-width
// viewport before content even started, with no toggle/collapse mechanism
// anywhere in the codebase. This is the mobile entry point that replaces
// both below the md breakpoint -- desktop IconRail/Sidebar get wrapped in
// `hidden md:flex` in layout.tsx instead of being touched directly, so
// nothing about the desktop experience changes.
export function MobileNav({ role }: { role: Role }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  const visible = DEPT_ROUTES.filter((d) => (d.roles as readonly string[]).includes(role));

  return (
    <>
      {/* Top bar — mobile only */}
      <header
        className="flex md:hidden items-center justify-between shrink-0"
        style={{
          height: "52px",
          backgroundColor: "#0e1218",
          borderBottom: "1px solid #1c222b",
          padding: "0 12px",
        }}
      >
        <button
          onClick={() => setOpen(true)}
          aria-label="Open navigation"
          className="flex flex-col items-center justify-center gap-[4px]"
          style={{ width: 44, height: 44 }}
        >
          <span style={{ width: 20, height: 2, backgroundColor: "#c7cfd6", borderRadius: 1 }} />
          <span style={{ width: 20, height: 2, backgroundColor: "#c7cfd6", borderRadius: 1 }} />
          <span style={{ width: 20, height: 2, backgroundColor: "#c7cfd6", borderRadius: 1 }} />
        </button>

        <p className="text-[13px] font-bold" style={{ color: "#eef2f5" }}>
          CEO DECODED
        </p>

        <div
          className="w-8 h-8 rounded-[8px] flex items-center justify-center text-[13px] font-bold shrink-0"
          style={{ backgroundColor: "#5eead4", color: "#0b0e13" }}
        >
          C
        </div>
      </header>

      {/* Drawer overlay — mobile only */}
      {open && (
        <div
          className="md:hidden fixed inset-0 z-50 flex"
          style={{ backgroundColor: "rgba(0,0,0,0.6)" }}
          onClick={() => setOpen(false)}
        >
          <nav
            className="flex flex-col py-4 h-full"
            style={{ width: "260px", backgroundColor: "#0e1218", borderRight: "1px solid #1c222b" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 mb-5">
              <div>
                <p className="text-[14px] font-bold tracking-wide" style={{ color: "#eef2f5" }}>
                  CEO DECODED
                </p>
                <p className="text-[10px] font-mono" style={{ color: "#5b6673" }}>
                  THD Agentic Systems LLC
                </p>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
                style={{ width: 44, height: 44, color: "#8b96a3" }}
                className="flex items-center justify-center text-xl"
              >
                ✕
              </button>
            </div>

            <ul className="flex flex-col gap-1 px-2 overflow-y-auto">
              {visible.map((dept) => {
                const active = pathname.startsWith(dept.path);
                return (
                  <li key={dept.id}>
                    <Link
                      href={dept.path}
                      onClick={() => setOpen(false)}
                      className="flex items-center gap-3 rounded-[8px] transition-colors"
                      style={{
                        padding: "12px 12px",
                        minHeight: 44,
                        backgroundColor: active ? "#5eead41a" : "transparent",
                        color: active ? "#5eead4" : "#c7cfd6",
                        fontWeight: active ? 600 : 400,
                        fontSize: "14px",
                        textDecoration: "none",
                      }}
                    >
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
                      <span className="truncate">{dept.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>
      )}
    </>
  );
}
