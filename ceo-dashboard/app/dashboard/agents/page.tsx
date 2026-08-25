"use client";

import { useEffect, useState, useCallback } from "react";
import { NovaHud } from "@/components/hud/NovaHud";
import { createClient } from "@/lib/supabase/client";
import type { VoiceAgentStatus } from "@/lib/types";

// Replaces the plain toggle-card panel with the real NOVA HUD (see
// components/hud/NovaHud.tsx), live-driven by jarvis-decoded's
// nova_agent_status table -- migration 011 (enable/heartbeat) + 012
// (current_state) + 013 (Realtime read policy). Initial fetch and every
// write still go through /api/agent-status (service-role, computes
// health/label server-side) -- Realtime here is only a low-latency
// "something changed, refetch" signal via the anon-key browser client,
// not a second source of truth, so the health-computation logic never
// has to be duplicated client-side.

const FALLBACK_POLL_MS = 15000; // safety net if a Realtime event is ever missed

export default function AgentsPage() {
  const [agents, setAgents] = useState<VoiceAgentStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Set<string>>(new Set());

  const fetchStatus = useCallback(async () => {
    const res = await fetch("/api/agent-status");
    if (!res.ok) return;
    const body = await res.json();
    setAgents(body.agents);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchStatus();
    const supabase = createClient();
    const channel = supabase
      .channel("nova_agent_status_hud")
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "nova_agent_status" },
        () => fetchStatus()
      )
      .subscribe();
    const fallback = setInterval(fetchStatus, FALLBACK_POLL_MS);
    return () => {
      supabase.removeChannel(channel);
      clearInterval(fallback);
    };
  }, [fetchStatus]);

  async function toggle(agentSlug: string, next: boolean) {
    setPending((prev) => new Set(prev).add(agentSlug));
    setAgents((prev) => prev.map((a) => (a.agent_slug === agentSlug ? { ...a, enabled: next } : a)));
    try {
      await fetch("/api/agent-status", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_slug: agentSlug, enabled: next }),
      });
    } finally {
      setPending((prev) => {
        const n = new Set(prev);
        n.delete(agentSlug);
        return n;
      });
      fetchStatus();
    }
  }

  const nova = agents.find((a) => a.agent_slug === "nova");
  const hudNodes = (["apollo", "counsel", "ledger", "board"] as const).map((slug) => {
    const a = agents.find((row) => row.agent_slug === slug);
    return { slug, label: a?.label ?? slug.toUpperCase(), enabled: a?.enabled ?? false };
  });

  return (
    <div className="relative h-full w-full">
      {loading ? (
        <div
          className="flex h-full w-full items-center justify-center font-mono text-[13px]"
          style={{ color: "#5b6673", backgroundColor: "#02060c" }}
        >
          Loading NOVA…
        </div>
      ) : (
        <NovaHud state={nova?.current_state ?? "idle"} nodes={hudNodes} />
      )}

      {/* Compact control strip -- enable/disable, not part of the HUD's
          own pixel-perfect 1920x1080 stage geometry. */}
      <div
        className="absolute top-4 right-4 flex flex-col gap-1.5 rounded-md p-3 font-mono text-[11px]"
        style={{ backgroundColor: "rgba(2,6,12,.75)", border: "1px solid rgba(0,240,255,.3)", backdropFilter: "blur(4px)" }}
      >
        {agents.map((a) => (
          <button
            key={a.agent_slug}
            type="button"
            disabled={pending.has(a.agent_slug)}
            onClick={() => toggle(a.agent_slug, !a.enabled)}
            className="flex items-center justify-between gap-3 rounded px-2 py-1 transition-colors"
            style={{
              border: `1px solid ${a.enabled ? "#00f0ff" : "#2a3542"}`,
              color: a.enabled ? "#00f0ff" : "#5b6673",
              opacity: pending.has(a.agent_slug) ? 0.5 : 1,
              cursor: pending.has(a.agent_slug) ? "not-allowed" : "pointer",
              background: "transparent",
            }}
          >
            <span>{a.label}</span>
            <span
              className="ml-2 inline-block h-2 w-2 rounded-full"
              style={{
                backgroundColor: a.health === "healthy" ? "#00ff88" : a.health === "unhealthy" ? "#ff0044" : "#5b6673",
                boxShadow: a.health === "off" ? "none" : `0 0 6px ${a.health === "healthy" ? "#00ff88" : "#ff0044"}`,
              }}
            />
          </button>
        ))}
      </div>
    </div>
  );
}
