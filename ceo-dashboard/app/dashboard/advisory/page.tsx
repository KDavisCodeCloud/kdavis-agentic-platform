import { createClient } from "@/lib/supabase/server";
import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import type { AdvisoryThread } from "@/lib/types";

const ADVISORS = [
  {
    role: "CFO",
    name: "Alex Rivera",
    accent: "#6fce8f",
    context: "Revenue strategy, exit gate math, burn rate",
    memory: "Currently tracking $0 MRR across 5 products. Primary focus: reaching $15K MRR × 3 months for CorVel exit gate. Burn is ~$225/mo on infra.",
  },
  {
    role: "CMO",
    name: "Jordan Lee",
    accent: "#7ea6f5",
    context: "Go-to-market, content strategy, pipeline growth",
    memory: "No active marketing campaigns. LinkedIn content agent not yet built. Sales pipeline empty. Focus: first paying subscriber acquisition.",
  },
  {
    role: "CTO",
    name: "Morgan Chen",
    accent: "#5eead4",
    context: "Architecture, agent design, technical debt",
    memory: "MSE research swarm live. CEO dashboard deploying. Week 2 agent (market sizing) next on cadence. n8n on Node 22, @langchain/core patched.",
  },
];

export default async function AdvisoryPage() {
  const supabase = await createClient();
  const { data: threads } = await supabase
    .from("advisory_threads")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(30);

  const allThreads = (threads ?? []) as AdvisoryThread[];

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Advisory" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Advisor cards */}
          <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
            {ADVISORS.map((advisor) => {
              const advisorThreads = allThreads.filter(
                (t) => t.advisor_role === advisor.role
              ).slice(0, 3);

              return (
                <SectionCard key={advisor.role} title="">
                  <div className="mb-3">
                    <p className="text-[15px] font-bold mb-0.5" style={{ color: advisor.accent }}>
                      {advisor.name}
                    </p>
                    <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                      {advisor.role} · {advisor.context}
                    </p>
                  </div>

                  {/* Thread preview */}
                  {advisorThreads.length > 0 ? (
                    <div className="space-y-2 mb-3">
                      {advisorThreads.map((t) => (
                        <div
                          key={t.id}
                          className="rounded-[8px] p-2.5"
                          style={{
                            backgroundColor: "#10151b",
                            border: "1px solid #1c222b",
                            borderLeft: `3px solid ${t.role === "advisor" ? advisor.accent : "#3a4250"}`,
                          }}
                        >
                          <p className="text-[11px] font-mono mb-0.5" style={{ color: "#5b6673" }}>
                            {t.role === "advisor" ? advisor.name : "You"}
                          </p>
                          <p className="text-[12px]" style={{ color: "#aab4bd" }}>
                            {t.message.slice(0, 120)}{t.message.length > 120 ? "…" : ""}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div
                      className="rounded-[8px] p-2.5 mb-3"
                      style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
                    >
                      <p className="text-[11px] font-mono" style={{ color: "#3a4250" }}>
                        No conversation yet
                      </p>
                    </div>
                  )}

                  {/* Memory Summary */}
                  <div className="mb-3">
                    <p className="text-[10px] font-mono uppercase mb-1" style={{ color: "#5b6673" }}>
                      Memory Summary
                    </p>
                    <p className="text-[11.5px]" style={{ color: "#8b96a3" }}>
                      {advisor.memory}
                    </p>
                  </div>

                  {/* Brief button */}
                  <button
                    className="w-full py-2 rounded-[8px] text-[11px] font-mono font-semibold transition-colors"
                    style={{ border: `1px solid ${advisor.accent}`, color: advisor.accent, backgroundColor: "transparent" }}
                  >
                    Brief this advisor
                    {/* TODO: wire to /ceo/advisory/brief — context push, thread scrollable, panel collapsible */}
                  </button>
                </SectionCard>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
