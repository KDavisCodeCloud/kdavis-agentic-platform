type Status = string;

const BADGE_MAP: Record<string, { color: string; bg: string; label: string }> = {
  assigned:        { color: "#7ea6f5", bg: "#5b8def22", label: "Assigned" },
  in_progress:     { color: "#5eead4", bg: "#5eead422", label: "In Progress" },
  submitted:       { color: "#e8963f", bg: "#e8963f22", label: "Submitted" },
  approved:        { color: "#6fce8f", bg: "#6fce8f22", label: "Approved" },
  revision_needed: { color: "#e05d5d", bg: "#e05d5d22", label: "Revision" },
  completed:       { color: "#9aa2ab", bg: "#2a2a2a",   label: "Completed" },
  high:            { color: "#e05d5d", bg: "#e05d5d22", label: "High" },
  normal:          { color: "#7ea6f5", bg: "#5b8def22", label: "Normal" },
  low:             { color: "#9aa2ab", bg: "#2a2a2a",   label: "Low" },
  active:          { color: "#6fce8f", bg: "#6fce8f22", label: "Active" },
  pending:         { color: "#e8963f", bg: "#e8963f22", label: "Pending" },
};

export function StatusBadge({ status, pill }: { status: Status; pill?: boolean }) {
  const map = BADGE_MAP[status] ?? { color: "#9aa2ab", bg: "#2a2a2a", label: status };
  return (
    <span
      className="shrink-0 text-[10px] font-mono font-semibold px-1.5 py-0.5"
      style={{
        color: map.color,
        backgroundColor: map.bg,
        borderRadius: pill ? "20px" : "5px",
        whiteSpace: "nowrap",
      }}
    >
      {map.label}
    </span>
  );
}
