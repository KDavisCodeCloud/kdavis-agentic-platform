"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { StatusBadge } from "./StatusBadge";
import type { MonitoringEvent } from "@/lib/types";

interface MonitoringEventRowProps {
  item: MonitoringEvent;
  onResolved?: () => void;
}

export function MonitoringEventRow({ item, onResolved }: MonitoringEventRowProps) {
  const [loading, setLoading] = useState(false);
  const supabase = createClient();

  // "acknowledged" leaves the event visible elsewhere for reference but off
  // this open-only panel; "dismissed" is a real resolution the same way
  // HitlApprovalRow's "rejected" is -- both stamp resolved_at, neither sets
  // resolved_by (HitlApprovalRow's own precedent: no user-identity plumbing
  // exists in this dashboard yet to fill it honestly).
  async function resolve(action: "acknowledged" | "dismissed") {
    setLoading(true);
    await supabase
      .from("mse_monitoring_events")
      .update({ status: action, resolved_at: new Date().toISOString() })
      .eq("id", item.id);
    setLoading(false);
    onResolved?.();
  }

  if (item.status !== "open") return null;

  return (
    <div className="py-3 min-w-0" style={{ borderTop: "1px solid #1c222b" }}>
      {/* Product + severity */}
      <div className="flex items-center gap-2 mb-1 min-w-0">
        <span className="text-[12.5px] font-semibold truncate-text" style={{ color: "#eef2f5" }}>
          {item.product_name}
        </span>
        <StatusBadge status={item.severity ?? "healthy"} />
      </div>

      {/* Recommended action */}
      <p className="text-[12px] mb-2 truncate-text" style={{ color: "#aab4bd" }}>
        {item.recommended_action ?? "No recommended action recorded."}
      </p>

      {/* Triggered thresholds */}
      {item.triggered_thresholds?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {item.triggered_thresholds.map((t, i) => (
            <span
              key={i}
              className="text-[10px] font-mono px-1.5 py-0.5 rounded"
              style={{ backgroundColor: "#1c222b", color: "#8b96a3" }}
            >
              {t.metric}: {t.value}/{t.threshold}
            </span>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => resolve("acknowledged")}
          disabled={loading}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
          style={{ border: "1px solid #5eead4", color: "#5eead4", backgroundColor: "transparent" }}
        >
          Acknowledge
        </button>
        <button
          onClick={() => resolve("dismissed")}
          disabled={loading}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
          style={{ border: "1px solid #3a4250", color: "#8b96a3", backgroundColor: "transparent" }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
