import type { ReactNode } from "react";
import { DataStatus } from "./DataStatus";

interface SectionCardProps {
  title: string;
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
  // Whether this section reads real data or is still a static mock — see
  // DataStatus.tsx. Omit only for sections that are pure layout/no data
  // (rare) — every data-bearing section should set this explicitly.
  status?: "live" | "partial" | "not_built";
  statusNote?: string;
}

export function SectionCard({ title, children, className = "", style, status, statusNote }: SectionCardProps) {
  return (
    <div
      className={`rounded-card ${className}`}
      style={{
        backgroundColor: "#141a22",
        border: "1px solid #1c222b",
        padding: "20px",
        ...style,
      }}
    >
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3.5">
        <p className="text-[13px] font-bold" style={{ color: "#c7cfd6" }}>
          {title}
        </p>
        {status && <DataStatus status={status} note={statusNote} />}
      </div>
      {children}
    </div>
  );
}
