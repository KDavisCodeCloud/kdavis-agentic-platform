"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { StatusBadge } from "./StatusBadge";
import { ProgressBar } from "./ProgressBar";
import type { HitlItem, BlastRadius } from "@/lib/types";

const BLAST_COLORS: Record<BlastRadius, string> = {
  low:    "#6fce8f",
  medium: "#e8963f",
  high:   "#e05d5d",
};

interface HitlApprovalRowProps {
  item: HitlItem;
  onResolved?: () => void;
}

export function HitlApprovalRow({ item, onResolved }: HitlApprovalRowProps) {
  const [loading, setLoading] = useState(false);
  const supabase = createClient();

  async function resolve(action: "approved" | "rejected") {
    setLoading(true);
    await supabase
      .from("hitl_queue")
      .update({ status: action, resolved_at: new Date().toISOString() })
      .eq("id", item.id);
    setLoading(false);
    onResolved?.();
  }

  if (item.status !== "pending") return null;

  return (
    <div
      className="py-3 min-w-0"
      style={{ borderTop: "1px solid #1c222b" }}
    >
      {/* Agent + blast radius */}
      <div className="flex items-center gap-2 mb-1 min-w-0">
        <span className="text-[12.5px] font-semibold truncate-text" style={{ color: "#eef2f5" }}>
          {item.agent_name}
        </span>
        <span
          className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: `${BLAST_COLORS[item.blast_radius]}22`,
            color: BLAST_COLORS[item.blast_radius],
          }}
        >
          {item.blast_radius.toUpperCase()} RADIUS
        </span>
      </div>

      {/* Proposed action */}
      <p className="text-[12px] mb-2 truncate-text" style={{ color: "#aab4bd" }}>
        {item.proposed_action}
      </p>

      {/* Confidence bar */}
      <div className="flex items-center gap-2 mb-3">
        <div className="flex-1">
          <ProgressBar value={item.confidence_pct} accent="#5eead4" />
        </div>
        <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
          {item.confidence_pct}% conf.
        </span>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => resolve("approved")}
          disabled={loading}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
          style={{ border: "1px solid #5eead4", color: "#5eead4", backgroundColor: "transparent" }}
        >
          Approve
        </button>
        <button
          onClick={() => resolve("rejected")}
          disabled={loading}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
          style={{ border: "1px solid #3a4250", color: "#8b96a3", backgroundColor: "transparent" }}
        >
          Reject
        </button>
        {/* TODO: batch-approve for 3+ similar items — not yet built */}
      </div>
    </div>
  );
}
