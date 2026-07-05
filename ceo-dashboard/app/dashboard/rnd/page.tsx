"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { AgentRosterCard } from "@/components/ui/AgentRosterCard";
import { ProgressBar } from "@/components/ui/ProgressBar";
import type { OpportunityPipelineItem } from "@/lib/types";

const MSE_AGENTS = [
  { name: "Dispatch",  status: "active",   focus: "Orchestrator — all 6 verticals",  lastRun: "last session" },
  { name: "Verdict",  status: "active",   focus: "7-gate quality filter",            lastRun: "last session" },
  { name: "Ledger",   status: "pending",  focus: "Finance vertical intel",           lastRun: null },
  { name: "Anchor",   status: "pending",  focus: "Real estate vertical intel",       lastRun: null },
  { name: "Comply",   status: "pending",  focus: "Legal vertical intel",             lastRun: null },
  { name: "Runway",   status: "pending",  focus: "HR/ops vertical intel",            lastRun: null },
  { name: "Pulse",    status: "pending",  focus: "Healthcare vertical intel",        lastRun: null },
  { name: "Scout",    status: "pending",  focus: "E-commerce vertical intel",        lastRun: null },
];

const BUILD_PIPELINE = [
  { product: "Cloud Decoded",     day: 0,  total: 29, phase: "Pre-build",  mrr: "$4K floor" },
  { product: "Micro SaaS Engine", day: 0,  total: 29, phase: "Pre-build",  mrr: "$4K floor" },
];

export default function RndPage() {
  const supabase = createClient();
  const [opportunities, setOpportunities] = useState<OpportunityPipelineItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    const { data } = await supabase
      .from("opportunity_pipeline")
      .select("id, vertical, pain_point, solution_concept, conservative_mrr_potential, build_confidence_score, status, competition_density, created_at")
      .order("build_confidence_score", { ascending: false })
      .limit(20);
    setOpportunities((data ?? []) as OpportunityPipelineItem[]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function runResearchSwarm() {
    await fetch(`${process.env.NEXT_PUBLIC_MSE_API_URL}/research/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer internal" },
      body: JSON.stringify({ verticals: ["Healthcare / Medical Front Desk", "Legal / Professional Services", "E-commerce / Retail Ops", "Real Estate / Property Management", "HR / Ops / People Management", "Finance / Accounting / Bookkeeping"] }),
    });
    alert("Research swarm started. Results will appear in the opportunity pipeline in ~2–3 minutes.");
  }

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="R&D">
        <button
          onClick={runResearchSwarm}
          className="px-3 py-1.5 rounded-[8px] text-[11px] font-mono font-semibold"
          style={{ border: "1px solid #5eead4", color: "#5eead4", backgroundColor: "transparent" }}
        >
          Run Research Swarm
        </button>
      </TopBar>

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Opportunity Pipeline */}
          <SectionCard title="Opportunity Pipeline">
            {loading ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading pipeline…</p>
            ) : opportunities.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                Pipeline is empty. Click "Run Research Swarm" above to populate it.
              </p>
            ) : (
              opportunities.map((opp) => (
                <div
                  key={opp.id}
                  className="flex items-center gap-3 py-2.5 min-w-0"
                  style={{ borderTop: "1px solid #1c222b" }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 min-w-0">
                      <p className="text-[12.5px] font-semibold truncate-text min-w-0" style={{ color: "#eef2f5" }}>
                        {opp.solution_concept}
                      </p>
                    </div>
                    <p className="text-[11px] font-mono truncate-text" style={{ color: "#5b6673" }}>
                      {opp.vertical} — ${Number(opp.conservative_mrr_potential).toLocaleString()}/mo potential
                    </p>
                    {/* TODO: click-through to full agent output drawer (not yet built) */}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[11px] font-mono" style={{ color: "#8b96a3" }}>
                      {opp.build_confidence_score ?? 0}%
                    </span>
                    <StatusBadge status={opp.status} />
                  </div>
                </div>
              ))
            )}
          </SectionCard>

          {/* MSE Agent Swarm */}
          <SectionCard title="MSE Agent Swarm">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              {MSE_AGENTS.map((a) => (
                <AgentRosterCard key={a.name} {...a} />
              ))}
            </div>
          </SectionCard>

          {/* Build Pipeline */}
          <SectionCard title="Build Pipeline">
            {BUILD_PIPELINE.map((p) => (
              <div
                key={p.product}
                className="py-3 min-w-0"
                style={{ borderTop: "1px solid #1c222b" }}
              >
                <div className="flex items-center justify-between mb-2 min-w-0">
                  <span className="text-[12.5px] font-semibold" style={{ color: "#eef2f5" }}>{p.product}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                      Day {p.day}/{p.total}
                    </span>
                    <StatusBadge status="planning" />
                  </div>
                </div>
                <p className="text-[11px] font-mono mb-2" style={{ color: "#8b96a3" }}>
                  Phase: {p.phase} · {p.mrr} enforced at DB level
                </p>
                <ProgressBar value={(p.day / p.total) * 100} accent="#5eead4" />
              </div>
            ))}
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
