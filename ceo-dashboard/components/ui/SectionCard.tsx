import type { ReactNode } from "react";

interface SectionCardProps {
  title: string;
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export function SectionCard({ title, children, className = "", style }: SectionCardProps) {
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
      <p
        className="text-[13px] font-bold mb-3.5"
        style={{ color: "#c7cfd6" }}
      >
        {title}
      </p>
      {children}
    </div>
  );
}
