import { StatusBadge } from "./StatusBadge";
import type { AgentEvent } from "@/lib/types";

const VERDICT_COLORS = {
  pass:    "#6fce8f",
  flagged: "#e05d5d",
  pending: "#e8963f",
} as const;

interface ActivityFeedRowProps {
  event: AgentEvent;
}

export function ActivityFeedRow({ event }: ActivityFeedRowProps) {
  const dotColor = VERDICT_COLORS[event.verdict] ?? "#9aa2ab";
  const ts = new Date(event.created_at);
  const time = ts.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      className="flex items-center gap-2 py-2 min-w-0"
      style={{ borderTop: "1px solid #1c222b" }}
    >
      {/* Status dot */}
      <span
        className="shrink-0 w-2 h-2 rounded-full"
        style={{ backgroundColor: dotColor }}
      />

      {/* Agent name */}
      <span
        className="text-[12px] font-semibold shrink-0 truncate-text"
        style={{ maxWidth: "100px", color: "#eef2f5" }}
      >
        {event.agent_name}
      </span>

      {/* Department */}
      <span
        className="text-[11px] font-mono shrink-0 truncate-text"
        style={{ maxWidth: "70px", color: "#5b6673" }}
      >
        {event.department}
      </span>

      {/* Action — flex takes remaining space, must truncate */}
      <span
        className="text-[12px] flex-1 truncate-text min-w-0"
        style={{ color: "#aab4bd" }}
      >
        {event.action}
      </span>

      <StatusBadge status={event.verdict} />

      <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
        {time}
      </span>
    </div>
  );
}
