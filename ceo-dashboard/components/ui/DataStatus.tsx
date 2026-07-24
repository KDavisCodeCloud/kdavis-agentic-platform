// Marks a dashboard section as live (real query, updates as data changes),
// partial (some real fields, some still hardcoded placeholder values), or
// not_built (the whole section is a static mock, no query behind it at all).
//
// Added 2026-07-24: most of this dashboard's sections silently showed
// hardcoded zeros/mock rows indistinguishable from real data — there was
// no way to tell, at a glance, what was actually wired up. This makes
// that distinction explicit everywhere instead of letting a placeholder
// read as a real "0" or "Not yet built" text buried in a table cell.

type Status = "live" | "partial" | "not_built";

const STYLE: Record<Status, { text: string; bg: string; label: string }> = {
  live:      { text: "#6fce8f", bg: "#6fce8f22", label: "LIVE" },
  partial:   { text: "#e8963f", bg: "#e8963f22", label: "PARTIALLY LIVE" },
  not_built: { text: "#9aa2ab", bg: "#2a2a2a",   label: "NOT YET BUILT" },
};

interface DataStatusProps {
  status: Status;
  // Optional extra context, e.g. "reads opportunity_pipeline" or
  // "no query wired — static mock data".
  note?: string;
}

export function DataStatus({ status, note }: DataStatusProps) {
  const s = STYLE[status];
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-flex items-center font-mono font-semibold"
        style={{
          fontSize: "9.5px",
          padding: "2px 7px",
          borderRadius: "5px",
          backgroundColor: s.bg,
          color: s.text,
          whiteSpace: "nowrap",
          letterSpacing: "0.03em",
        }}
      >
        {s.label}
      </span>
      {note && (
        <span className="text-[10px] font-mono" style={{ color: "#5b6673" }}>
          {note}
        </span>
      )}
    </span>
  );
}
