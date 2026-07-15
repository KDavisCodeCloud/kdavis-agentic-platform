import type { BadgeStatus } from "@/lib/types";

const STATUS_MAP: Record<string, { text: string; bg: string; label?: string }> = {
  active:         { text: "#6fce8f", bg: "#6fce8f22" },
  pass:           { text: "#6fce8f", bg: "#6fce8f22" },
  healthy:        { text: "#6fce8f", bg: "#6fce8f22" },
  complete:       { text: "#6fce8f", bg: "#6fce8f22" },
  published:      { text: "#6fce8f", bg: "#6fce8f22" },
  approved:       { text: "#6fce8f", bg: "#6fce8f22" },
  done:           { text: "#6fce8f", bg: "#6fce8f22" },
  closed:         { text: "#6fce8f", bg: "#6fce8f22" },
  READY_TO_BUILD: { text: "#6fce8f", bg: "#6fce8f22", label: "READY" },
  building:       { text: "#7ea6f5", bg: "#5b8def22" },
  pending:        { text: "#7ea6f5", bg: "#5b8def22" },
  queued:         { text: "#7ea6f5", bg: "#5b8def22" },
  in_progress:    { text: "#7ea6f5", bg: "#5b8def22" },
  rendering:      { text: "#7ea6f5", bg: "#5b8def22" },
  validated:      { text: "#7ea6f5", bg: "#5b8def22" },
  executing:      { text: "#7ea6f5", bg: "#5b8def22" },
  executed:       { text: "#6fce8f", bg: "#6fce8f22" },
  budget_exceeded:{ text: "#e05d5d", bg: "#e05d5d22" },
  planning:       { text: "#e8963f", bg: "#e8963f22" },
  flagged:        { text: "#e8963f", bg: "#e8963f22" },
  watch:          { text: "#e8963f", bg: "#e8963f22" },
  degraded:       { text: "#e8963f", bg: "#e8963f22" },
  draft:          { text: "#e8963f", bg: "#e8963f22" },
  open:           { text: "#e8963f", bg: "#e8963f22" },
  P2:             { text: "#e8963f", bg: "#e8963f22" },
  P1:             { text: "#e05d5d", bg: "#e05d5d22" },
  error:          { text: "#e05d5d", bg: "#e05d5d22" },
  failed:         { text: "#e05d5d", bg: "#e05d5d22" },
  rejected:       { text: "#e05d5d", bg: "#e05d5d22" },
  paused:         { text: "#9aa2ab", bg: "#2a2a2a" },
  backlog:        { text: "#9aa2ab", bg: "#2a2a2a" },
  P3:             { text: "#9aa2ab", bg: "#2a2a2a" },
  read:           { text: "#9aa2ab", bg: "#2a2a2a" },
  write:          { text: "#7ea6f5", bg: "#5b8def22" },
  admin:          { text: "#5eead4", bg: "#5eead41a" },
  discovered:     { text: "#9aa2ab", bg: "#2a2a2a" },
};

interface StatusBadgeProps {
  status: string;
  pill?: boolean;
}

export function StatusBadge({ status, pill = false }: StatusBadgeProps) {
  const s = STATUS_MAP[status] ?? { text: "#9aa2ab", bg: "#2a2a2a" };
  const label = s.label ?? status.replace(/_/g, " ").toUpperCase();

  return (
    <span
      className="inline-flex items-center font-mono font-semibold"
      style={{
        fontSize: "10px",
        padding: "2px 7px",
        borderRadius: pill ? "20px" : "5px",
        backgroundColor: s.bg,
        color: s.text,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}
