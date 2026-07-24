interface MetricCardProps {
  label: string;
  value: string;
  subtext?: string;
  accent?: string; // hex color
  // Compact live/not-built indicator — full DataStatus badge is too heavy
  // for this card's density. Omit only for non-data decorative cards.
  live?: boolean;
}

const LIVE_DOT_COLOR = { true: "#6fce8f", false: "#9aa2ab" };

export function MetricCard({
  label,
  value,
  subtext,
  accent = "#5eead4",
  live,
}: MetricCardProps) {
  return (
    <div
      className="rounded-card p-4"
      style={{
        background: `linear-gradient(150deg, ${accent}24 0%, #141a22 75%)`,
        border: "1px solid #1c222b",
        padding: "16px 18px",
        position: "relative",
      }}
    >
      {live !== undefined && (
        <span
          title={live ? "Live data" : "Not yet built — placeholder value"}
          className="inline-block rounded-full"
          style={{
            position: "absolute", top: "12px", right: "12px",
            width: "6px", height: "6px",
            backgroundColor: LIVE_DOT_COLOR[live ? "true" : "false"],
          }}
        />
      )}
      <p
        className="text-[11px] font-mono uppercase tracking-wider mb-2"
        style={{ color: "#5b6673" }}
      >
        {label}
      </p>
      <p className="text-[24px] font-extrabold leading-none mb-1.5" style={{ color: accent }}>
        {value}
      </p>
      {subtext && (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          {subtext}
        </p>
      )}
    </div>
  );
}
