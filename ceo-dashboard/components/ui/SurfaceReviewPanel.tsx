"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { MseContentSurface, MseProduct } from "@/lib/types";

// DIST Phase 5 (2026-08-30). Tier 2 (jtbd/calculator) batch review --
// "reviewed as a set with bulk approve/reject" per spec. Deliberately
// scoped to hitl_tier=2 only: Tier 1 auto-publishes (never sits here),
// Tier 3 is owner-only/individual and must never be batchable (a
// competitor claim or jurisdiction page carries legal/regulatory
// exposure a bulk click shouldn't touch) -- enforced twice: this query
// filters hitl_tier=2 server-side, and bulk approve additionally guards
// client-side against a Tier 3 row ever entering the selection set.
//
// Approve calls the real admin-gated publish_surface() RPC (migration
// 032) -- the same function a human uses one at a time, just looped.
// Reject sets status='archived' directly (a real UPDATE, not gated the
// same way 'published' is) -- terminal, distinct from quality_gate.py's
// own 'draft' demotion on an automated rejection, since a human
// rejecting a page that already passed the automated gate is a final
// call, not something the generator should silently retry.
//
// mse_content_surfaces isn't in supabase_realtime's publication (same as
// every other DIST table) -- 60s poll, matching AttributionFunnelPanel's
// own established convention.
export function SurfaceReviewPanel() {
  const supabase = createClient();
  const [products, setProducts] = useState<Record<string, MseProduct>>({});
  const [surfaces, setSurfaces] = useState<MseContentSurface[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const fetchData = useCallback(async () => {
    const [productsRes, surfacesRes] = await Promise.all([
      supabase.from("mse_products").select("*"),
      supabase
        .from("mse_content_surfaces")
        .select("*")
        .eq("hitl_tier", 2)
        .eq("status", "pending_review")
        .order("created_at", { ascending: false }),
    ]);
    if (productsRes.data) {
      const byId: Record<string, MseProduct> = {};
      for (const p of productsRes.data as MseProduct[]) byId[p.id] = p;
      setProducts(byId);
    }
    if (surfacesRes.data) setSurfaces(surfacesRes.data as MseContentSurface[]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function bulkApprove() {
    setBusy(true);
    // Second guard, belt-and-suspenders with the server-side hitl_tier=2
    // filter above: never call publish_surface for anything not in the
    // currently-loaded Tier 2 set.
    const eligible = surfaces.filter((s) => selected.has(s.id) && s.hitl_tier === 2);
    for (const s of eligible) {
      await supabase.rpc("publish_surface", { p_id: s.id });
    }
    setSelected(new Set());
    await fetchData();
    setBusy(false);
  }

  async function bulkReject() {
    setBusy(true);
    const ids = surfaces.filter((s) => selected.has(s.id) && s.hitl_tier === 2).map((s) => s.id);
    if (ids.length > 0) {
      await supabase.from("mse_content_surfaces").update({ status: "archived" }).in("id", ids);
    }
    setSelected(new Set());
    await fetchData();
    setBusy(false);
  }

  if (loading) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        Loading surface queue…
      </p>
    );
  }

  if (surfaces.length === 0) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        No Tier 2 surfaces awaiting review.
      </p>
    );
  }

  return (
    <>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          {selected.size} selected of {surfaces.length}
        </span>
        <div className="flex gap-2">
          <button
            onClick={bulkApprove}
            disabled={busy || selected.size === 0}
            className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors disabled:opacity-40"
            style={{ border: "1px solid #5eead4", color: "#5eead4", backgroundColor: "transparent" }}
          >
            Approve Selected
          </button>
          <button
            onClick={bulkReject}
            disabled={busy || selected.size === 0}
            className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors disabled:opacity-40"
            style={{ border: "1px solid #3a4250", color: "#8b96a3", backgroundColor: "transparent" }}
          >
            Reject Selected
          </button>
        </div>
      </div>
      <div className="space-y-2">
        {surfaces.map((s) => (
          <label
            key={s.id}
            className="flex items-center gap-3 py-2 px-2 cursor-pointer"
            style={{ borderTop: "1px solid #1c222b" }}
          >
            <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggle(s.id)} />
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
              style={{ backgroundColor: "#1c222b", color: "#8b96a3" }}
            >
              {s.archetype}
            </span>
            <span className="text-[12px] font-semibold truncate-text" style={{ color: "#eef2f5" }}>
              {s.title}
            </span>
            <span className="text-[11px] font-mono ml-auto shrink-0" style={{ color: "#5b6673" }}>
              {products[s.product_id]?.name ?? s.product_id}
            </span>
          </label>
        ))}
      </div>
    </>
  );
}
