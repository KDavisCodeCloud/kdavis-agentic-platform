"use client";

import { useEffect, useState } from "react";
import { StatusBadge } from "./StatusBadge";
import { fetchMseCampaignStatus } from "@/lib/email-campaigns-api";
import type { MseCampaignStatus } from "@/lib/types";

// "Generate Campaign" per product isn't wired here: the real trigger
// (POST /products/{id}/run-campaign in kdavis-microsaas-engine) keys
// product_id off opportunity_pipeline.id, but this campaign-status
// endpoint returns mse_products.id -- calling it with the wrong id would
// 404 silently or hit the wrong product. mse_products now has an
// opportunity_id column (session 2026-09-21 reconciliation) but
// campaign-status doesn't expose it yet. Documented as a gap rather than
// wiring a button that could fire the wrong product's campaign.
export function EmailCampaignMseStatusPanel() {
  const [status, setStatus] = useState<MseCampaignStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMseCampaignStatus()
      .then(setStatus)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading…</p>;
  if (error) return <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>MSE feed: {error}</p>;
  if (!status) return null;

  return (
    <div>
      <p className="text-[11px] font-mono mb-3" style={{ color: "#8b96a3" }}>
        {status.emailSequencesTotal} email sequence(s) exist, {status.emailSequencesUnattributable} unattributable to a real product.
        {status.note ? ` ${status.note}` : ""}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #1c222b" }}>
              {["Product", "Status", "Positioning", "Version"].map((h) => (
                <th key={h} className="text-[10px] font-mono uppercase py-2 pr-3" style={{ color: "#5b6673" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {status.products.map((p) => (
              <tr key={p.productId} style={{ borderBottom: "1px solid #161b22" }}>
                <td className="py-2 pr-3 text-[12px]" style={{ color: "#eef2f5" }}>{p.name} <span style={{ color: "#5b6673" }}>({p.slug})</span></td>
                <td className="py-2 pr-3"><StatusBadge status={p.productStatus} /></td>
                <td className="py-2 pr-3"><StatusBadge status={p.positioningStatus} /></td>
                <td className="py-2 pr-3 text-[11px] font-mono" style={{ color: "#8b96a3" }}>{p.positioningVersion ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] font-mono mt-3" style={{ color: "#5b6673" }}>
        &quot;Generate Campaign&quot; isn&apos;t wired here — the real trigger needs an opportunity_pipeline id this
        endpoint doesn&apos;t expose yet. Fire it from the MSE repo&apos;s own API directly, or extend campaign-status
        to include opportunity_id first.
      </p>
    </div>
  );
}
