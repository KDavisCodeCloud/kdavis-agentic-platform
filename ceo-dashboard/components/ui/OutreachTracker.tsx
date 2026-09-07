"use client";

import { useEffect, useState } from "react";
import { fetchOutreachSummary, type OutreachSummaryRow } from "@/lib/api";

// Real per-product outreach stats (mse_dm_sequences.touch_1_sent_at +
// mse_leads.stage) -- replaces the old static single-row mock. Grouped by
// product, not a named "sequence" (mse_dm_sequences rows are generated
// per-lead, there's no sequence-template concept in this schema to group
// by instead). "Meetings" is an honest approximation -- leads currently at
// stage 'demo' or later, set by a human on the leads page after a real
// call, not a calendar integration (none exists). Open rate has no real
// signal anywhere in this codebase (no email-open tracking) and is shown
// as "not tracked," never a fabricated percentage.
export function OutreachTracker() {
  const [rows, setRows] = useState<OutreachSummaryRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchOutreachSummary()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : "Loading outreach summary failed"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading…</p>;
  }
  if (error) {
    return <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>{error}</p>;
  }
  if (!rows.length) {
    return <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>No outreach sent yet.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {["Product", "Sent", "Open Rate", "Meetings"].map((h) => (
              <th
                key={h}
                className="text-left font-mono font-semibold"
                style={{ color: "#5b6673", borderBottom: "1px solid #1c222b", paddingBottom: "8px", paddingRight: "16px" }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.product_id}>
              <td className="font-semibold" style={{ color: "#eef2f5", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                {row.name}
              </td>
              <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                {row.sent}
              </td>
              <td className="font-mono" style={{ color: "#5b6673", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                not tracked
              </td>
              <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 0", borderTop: "1px solid #1c222b" }}>
                {row.meetings}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
