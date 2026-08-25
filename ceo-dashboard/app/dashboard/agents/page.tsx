"use client";

import { useEffect, useState, useCallback } from "react";
import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { VoiceAgentCard } from "@/components/ui/VoiceAgentCard";
import type { VoiceAgentStatus } from "@/lib/types";

// Polls GET/PATCH /api/agent-status, which reads/writes jarvis-decoded's
// nova_agent_status Supabase table directly -- no connection to
// nova-api.service or the Cloudflare tunnel at all. Plain setInterval +
// fetch, matching this repo's existing polling convention (no SWR/React
// Query anywhere here) -- see components/FireButton.tsx.

const POLL_INTERVAL_MS = 5000;

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
    const timer = setInterval(fetchStatus, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
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
        const next = new Set(prev);
        next.delete(agentSlug);
        return next;
      });
      fetchStatus();
    }
  }

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Voice Agents" />
      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          <SectionCard
            title="Voice Agent Roster"
            status="live"
            statusNote="nova_agent_status -- toggle writes here, nova-voice.service polls + heartbeats here"
          >
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              {loading ? (
                <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                  Loading…
                </p>
              ) : (
                agents.map((a) => (
                  <VoiceAgentCard
                    key={a.agent_slug}
                    label={a.label}
                    enabled={a.enabled}
                    health={a.health}
                    statusDetail={a.status_detail}
                    disabled={pending.has(a.agent_slug)}
                    onToggle={(next) => toggle(a.agent_slug, next)}
                  />
                ))
              )}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
