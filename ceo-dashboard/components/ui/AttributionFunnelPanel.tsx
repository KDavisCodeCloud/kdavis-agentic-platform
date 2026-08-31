"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { FUNNEL_STEPS, type MseFunnelEvent, type MseProduct } from "@/lib/types";

// DIST Phase 1 (2026-08-30). Queries mse_funnel_events directly (grouped
// client-side by product + step) rather than only mse_attribution_summary
// -- that view rolls up to signups/paid only, which can't show real
// per-step drop-off. mse_funnel_events isn't in supabase_realtime's
// publication (same as every other DIST table -- these are low-frequency
// business events, not something that needs sub-second live updates), so
// this refetches on mount and on a 60s interval rather than subscribing,
// matching MonitoringEventsPanel.tsx's loading/empty-state conventions
// without inventing a new one.
export function AttributionFunnelPanel() {
  const supabase = createClient();
  const [products, setProducts] = useState<MseProduct[]>([]);
  const [events, setEvents] = useState<MseFunnelEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    const [productsRes, eventsRes] = await Promise.all([
      supabase.from("mse_products").select("*"),
      supabase.from("mse_funnel_events").select("*"),
    ]);
    if (productsRes.data) setProducts(productsRes.data as MseProduct[]);
    if (eventsRes.data) setEvents(eventsRes.data as MseFunnelEvent[]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        Loading funnel…
      </p>
    );
  }

  if (products.length === 0) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        No products registered yet.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {products.map((product) => {
        const productEvents = events.filter((e) => e.product_id === product.id);
        const countsByStep: Record<string, number> = {};
        for (const step of FUNNEL_STEPS) {
          countsByStep[step] = productEvents.filter((e) => e.step === step).length;
        }
        const hasAnyData = Object.values(countsByStep).some((c) => c > 0);

        return (
          <div key={product.id}>
            <p className="text-[12.5px] font-semibold mb-2 truncate-text" style={{ color: "#eef2f5" }}>
              {product.name}
            </p>
            {!hasAnyData ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No funnel events recorded yet.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {FUNNEL_STEPS.map((step) => (
                  <div
                    key={step}
                    className="flex items-center gap-1.5 text-[10px] font-mono px-2 py-1 rounded"
                    style={{ backgroundColor: "#1c222b", color: "#8b96a3" }}
                  >
                    <span>{step}</span>
                    <span className="font-bold" style={{ color: "#eef2f5" }}>{countsByStep[step]}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
