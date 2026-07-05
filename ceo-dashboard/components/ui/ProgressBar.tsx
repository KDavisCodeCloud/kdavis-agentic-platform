interface ProgressBarProps {
  value: number; // 0-100
  accent?: string;
  height?: number;
}

export function ProgressBar({ value, accent = "#5eead4", height = 5 }: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div
      className="w-full rounded-full overflow-hidden"
      style={{ height, backgroundColor: "#1c222b" }}
    >
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${pct}%`, backgroundColor: accent }}
      />
    </div>
  );
}
