"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { TopBar } from "@/components/shell/TopBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { HITLQueuePanel } from "@/components/ui/HITLQueuePanel";
import { ActivityFeedRow } from "@/components/ui/ActivityFeedRow";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { FireButton } from "@/components/ui/FireButton";
import type { AgentEvent } from "@/lib/types";

const PRODUCTS = [
  { name: "Cloud Decoded",      status: "building",  mrr: "$0",   agents: 4, queue: 2 },
  { name: "Micro SaaS Engine",  status: "building",  mrr: "$0",   agents: 8, queue: 1 },
  { name: "GTA 6 Hub",          status: "planning",  mrr: "$0",   agents: 0, queue: 0 },
  { name: "CEO Decoded",        status: "building",  mrr: "$0",   agents: 3, queue: 0 },
  { name: "Hustle Decoded",     status: "planning",  mrr: "$0",   agents: 0, queue: 0 },
  // TODO: link each tile to that product's dedicated dashboard
];

// Fire button wiring — Session 6. Only products with a live agent to trigger
// get one; the rest (GTA 6 Hub, Hustle Decoded) stay as-is until their agents exist.
const PRODUCT_FIRE_BUTTONS: Record<string, { agentId: string; label: string }> = {
  "Cloud Decoded":     { agentId: "research_agent",     label: "Run Research" },
  "Micro SaaS Engine": { agentId: "portfolio_monitor",  label: "Run Monitor" },
  // Was "sop_gap_detector" — no such file exists in agents/internal/; the
  // real gap-scan agent is gap_detector_agent.py.
  "CEO Decoded":       { agentId: "gap_detector_agent", label: "Run Gap Scan" },
};

const TEAM = [
  { name: "Kelvin",  role: "CEO",    access: "Full Access",         pending: 1 },
  { name: "Wife",    role: "COO",    access: "Marketing / Ops / HR",pending: 3 },
  { name: "Son",     role: "CTO",    access: "R&D / Tech (read)",   pending: 0 },
];

export default function OverviewPage() {
  const supabase = createClient();
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [hitlCount, setHitlCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchEvents = useCallback(async () => {
    const { data } = await supabase
      .from("agent_events")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(20);
    if (data) setEvents(data as AgentEvent[]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchEvents();

    // Realtime: agent_events
    const evtChannel = supabase
      .channel("agent_events_overview")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "agent_events" },
        (payload) => setEvents((prev) => [payload.new as AgentEvent, ...prev.slice(0, 19)])
      )
      .subscribe();

    // hitl_queue fetch + realtime now owned by HITLQueuePanel below.

    return () => {
      supabase.removeChannel(evtChannel);
    };
  }, [fetchEvents, supabase]);

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Overview" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="max-w-none space-y-5">
          {/* Metric cards */}
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}
          >
            <MetricCard label="Portfolio MRR"  value="$0"    subtext="5 products tracked"  accent="#5eead4" />
            <MetricCard label="Products Live"  value="0"     subtext="of 5 in portfolio"   accent="#6fce8f" />
            <MetricCard label="Open HITL Items" value={String(hitlCount)} subtext="pending approval" accent="#e8963f" />
            <MetricCard label="Stack Burn / mo" value="~$225" subtext="infra cost estimate" accent="#e05d5d" />
          </div>

          {/* All Products */}
          <SectionCard title="All Products">
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
            >
              {PRODUCTS.map((p) => {
                const fireButton = PRODUCT_FIRE_BUTTONS[p.name];
                return (
                  <div
                    key={p.name}
                    className="rounded-[10px] p-3.5"
                    style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
                  >
                    <div className="flex items-start justify-between gap-1 mb-2 min-w-0">
                      <p className="text-[12.5px] font-semibold truncate-text min-w-0" style={{ color: "#eef2f5" }}>
                        {p.name}
                      </p>
                      <StatusBadge status={p.status} />
                    </div>
                    <p className="text-[20px] font-extrabold mb-1" style={{ color: "#5eead4" }}>
                      {p.mrr}
                    </p>
                    <div className="flex gap-3 text-[11px] font-mono mb-3" style={{ color: "#5b6673" }}>
                      <span>{p.agents} agents</span>
                      <span>{p.queue} queue</span>
                    </div>
                    {fireButton && (
                      <FireButton
                        agentId={fireButton.agentId}
                        label={fireButton.label}
                        payload={{}}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </SectionCard>

          {/* Two-column: Activity Feed + HITL Queue */}
          <div
            className="grid gap-5"
            style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}
          >
            {/* Agent Activity Feed */}
            <SectionCard title="Agent Activity">
              {loading ? (
                <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                  Loading events…
                </p>
              ) : events.length === 0 ? (
                <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                  No agent events yet. Fire the research swarm to populate this feed.
                </p>
              ) : (
                events.map((e) => <ActivityFeedRow key={e.id} event={e} />)
              )}
            </SectionCard>

            {/* HITL Approval Queue */}
            <SectionCard title="HITL Approval Queue">
              <HITLQueuePanel onCountChange={setHitlCount} />
              {/* TODO: batch-approve UX for 3+ similar items */}
            </SectionCard>
          </div>

          {/* Team Ops */}
          <SectionCard title="Team Ops">
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
            >
              {TEAM.map((member) => (
                <div
                  key={member.name}
                  className="rounded-[10px] p-3.5"
                  style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div
                      className="w-7 h-7 rounded-[8px] flex items-center justify-center text-[11px] font-bold"
                      style={{ backgroundColor: "#5eead41a", color: "#5eead4" }}
                    >
                      {member.name[0]}
                    </div>
                    <div>
                      <p className="text-[12.5px] font-semibold" style={{ color: "#eef2f5" }}>
                        {member.name}
                      </p>
                      <p className="text-[10px] font-mono" style={{ color: "#5b6673" }}>
                        {member.role}
                      </p>
                    </div>
                  </div>
                  <p className="text-[11px] font-mono mb-1" style={{ color: "#8b96a3" }}>
                    {member.access}
                  </p>
                  <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                    {member.pending > 0 ? `${member.pending} pending items` : "No pending items"}
                  </p>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
