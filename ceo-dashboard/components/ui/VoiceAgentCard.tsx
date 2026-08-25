"use client";

import type { VoiceAgentHealth } from "@/lib/types";

// Deliberately a sibling of AgentRosterCard, not an extension of it --
// AgentRosterCard's status:string -> StatusBadge contract doesn't fit a
// boolean toggle + continuously-refreshing glow, and bolting on
// conditional props risks its 8 existing instances in
// app/dashboard/rnd/page.tsx. Same tile chrome, different job.

interface VoiceAgentCardProps {
  label: string;
  enabled: boolean;
  health: VoiceAgentHealth;
  statusDetail: string | null;
  disabled?: boolean;
  onToggle: (next: boolean) => void;
}

const HEALTH_COLOR: Record<VoiceAgentHealth, string> = {
  healthy: "#6fce8f",
  unhealthy: "#e05d5d",
  off: "#5b6673",
};

export function VoiceAgentCard({ label, enabled, health, statusDetail, disabled, onToggle }: VoiceAgentCardProps) {
  const color = HEALTH_COLOR[health];
  const description =
    health === "off" ? "Disabled" : health === "healthy" ? "Connected" : statusDetail || "No heartbeat";

  return (
    <div
      className="rounded-[10px] p-3.5 transition-opacity"
      style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", opacity: health === "off" ? 0.6 : 1 }}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-[13px] font-bold" style={{ color: "#eef2f5" }}>
          {label}
        </p>
        <span
          className={`w-2.5 h-2.5 rounded-full shrink-0 ${health === "healthy" ? "animate-pulse" : ""}`}
          style={{
            backgroundColor: color,
            boxShadow: health === "off" ? "none" : `0 0 8px 2px ${color}99`,
          }}
        />
      </div>
      <p className="text-[11px] font-mono mb-2" style={{ color: "#5b6673" }}>
        {description}
      </p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onToggle(!enabled)}
        className="px-3 py-1 rounded-[6px] text-[11px] font-mono font-semibold w-full transition-colors"
        style={{
          border: `1px solid ${enabled ? "#5eead4" : "#3a4250"}`,
          color: enabled ? "#5eead4" : "#8b96a3",
          backgroundColor: "transparent",
          opacity: disabled ? 0.5 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
      >
        {enabled ? "Enabled — tap to disable" : "Disabled — tap to enable"}
      </button>
    </div>
  );
}
