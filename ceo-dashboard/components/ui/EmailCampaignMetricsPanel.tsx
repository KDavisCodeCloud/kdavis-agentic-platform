"use client";

import { useEffect, useState } from "react";
import { fetchMetrics } from "@/lib/email-campaigns-api";
import type { EmailCampaignMetrics } from "@/lib/types";

function fmt(n: number | null): string {
  return n === null ? "not tracked yet" : n.toLocaleString();
}

export function EmailCampaignMetricsPanel() {
  const [cd, setCd] = useState<EmailCampaignMetrics[] | null>(null);
  const [mse, setMse] = useState<EmailCampaignMetrics[] | null>(null);
  const [cdError, setCdError] = useState<string | null>(null);
  const [mseError, setMseError] = useState<string | null>(null);

  useEffect(() => {
    fetchMetrics("cloud-decoded").then(setCd).catch((err) => setCdError(err instanceof Error ? err.message : "Failed to load"));
    fetchMetrics("mse").then(setMse).catch((err) => setMseError(err instanceof Error ? err.message : "Failed to load"));
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-mono uppercase mb-2" style={{ color: "#5b6673" }}>Cloud Decoded — by sequence</p>
        {cdError ? (
          <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>{cdError}</p>
        ) : !cd ? (
          <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading…</p>
        ) : cd.length === 0 ? (
          <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>No sends recorded yet.</p>
        ) : (
          <MetricsTable rows={cd} />
        )}
      </div>
      <div>
        <p className="text-[10px] font-mono uppercase mb-2" style={{ color: "#5b6673" }}>MSE — aggregate</p>
        {mseError ? (
          <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>{mseError}</p>
        ) : !mse ? (
          <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading…</p>
        ) : (
          <MetricsTable rows={mse} />
        )}
      </div>
    </div>
  );
}

function MetricsTable({ rows }: { rows: EmailCampaignMetrics[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #1c222b" }}>
            {["Sequence", "Sends", "Clicks", "Unsubscribes", "Conversions", "Revenue (est.)"].map((h) => (
              <th key={h} className="text-[10px] font-mono uppercase py-2 pr-3" style={{ color: "#5b6673" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.sequenceKey ?? i} style={{ borderBottom: "1px solid #161b22" }}>
              <td className="py-2 pr-3 text-[12px] font-mono" style={{ color: "#eef2f5" }}>{r.sequenceKey ?? "(all)"}</td>
              <td className="py-2 pr-3 text-[11px] font-mono" style={{ color: "#8b96a3" }}>{fmt(r.sends)}</td>
              <td className="py-2 pr-3 text-[11px] font-mono" style={{ color: "#8b96a3" }}>{fmt(r.clicks)}</td>
              <td className="py-2 pr-3 text-[11px] font-mono" style={{ color: "#8b96a3" }}>{fmt(r.unsubscribes)}</td>
              <td className="py-2 pr-3 text-[11px] font-mono" style={{ color: "#8b96a3" }}>{fmt(r.conversions)}</td>
              <td className="py-2 pr-3 text-[11px] font-mono" style={{ color: "#8b96a3" }}>{r.revenueUsd === null ? "not tracked yet" : `$${r.revenueUsd.toLocaleString()}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.some((r) => r.note) && (
        <p className="text-[10px] font-mono mt-2" style={{ color: "#5b6673" }}>{rows.find((r) => r.note)?.note}</p>
      )}
    </div>
  );
}
