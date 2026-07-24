import { createClient } from "@/lib/supabase/server";
import { TopBar } from "@/components/shell/TopBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { AgentRosterCard } from "@/components/ui/AgentRosterCard";
import { ProgressBar } from "@/components/ui/ProgressBar";
import type { StackItem } from "@/lib/types";

const MRR_TABLE = [
  { product: "Cloud Decoded",     mrr: 0,  subs: 0, churn: 0,   mom: "—" },
  { product: "Micro SaaS Engine", mrr: 0,  subs: 0, churn: 0,   mom: "—" },
  { product: "GTA 6 Hub",         mrr: 0,  subs: 0, churn: 0,   mom: "—" },
  { product: "CEO Decoded",       mrr: 0,  subs: 0, churn: 0,   mom: "—" },
  { product: "Hustle Decoded",    mrr: 0,  subs: 0, churn: 0,   mom: "—" },
];

// Exit gate: CorVel acquisition thesis
const EXIT_METRICS = [
  { label: "MRR Target",          value: "$15,000 / mo" },
  { label: "Consecutive Months",  value: "3" },
  { label: "Current MRR",         value: "$0" },
  { label: "Progress to Gate",    value: "0%" },
  { label: "ARR at Gate",         value: "$180,000" },
  { label: "Multiple Target",     value: "4–6×" },
  { label: "Projected Valuation", value: "$720K–$1.08M" },
];

const FINANCE_AGENTS = [
  { name: "Revenue Tracker",    status: "pending",  lastRun: null,          output: "No runs yet" },
  { name: "Cash Flow Monitor",  status: "pending",  lastRun: null,          output: "No runs yet" },
  { name: "Expense Categorizer",status: "pending",  lastRun: null,          output: "No runs yet" },
];

export default async function FinancePage() {
  const supabase = await createClient();
  const { data: stack } = await supabase
    .from("operating_stack")
    .select("*")
    .order("monthly_cost_usd", { ascending: false });

  const stackItems = (stack ?? []) as StackItem[];
  const totalBurn = stackItems.reduce((s, i) => s + (i.status === "active" ? i.monthly_cost_usd : 0), 0);

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Finance" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Metric cards */}
          <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
            <MetricCard label="Total MRR"     value="$0"   subtext="all products"       accent="#5eead4" live={false} />
            <MetricCard label="MoM Growth"    value="—"    subtext="no prior month"     accent="#6fce8f" live={false} />
            <MetricCard label="Runway"        value="—"    subtext="months remaining"   accent="#7ea6f5" live={false} />
            <MetricCard label="Stack Burn/mo" value={`$${totalBurn.toFixed(0)}`} subtext="active services" accent="#e05d5d" live={true} />
          </div>

          {/* MRR Breakdown */}
          <SectionCard title="MRR Breakdown" status="not_built" statusNote="static mock rows — no revenue_events wiring yet">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Product", "MRR", "Subscribers", "Churn", "MoM Δ"].map((h) => (
                      <th
                        key={h}
                        className="text-left pb-2 font-mono font-semibold"
                        style={{ color: "#5b6673", borderBottom: "1px solid #1c222b", paddingBottom: "8px" }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MRR_TABLE.map((row) => (
                    <tr key={row.product}>
                      {[row.product, `$${row.mrr}`, row.subs, `${row.churn}%`, row.mom].map((cell, i) => (
                        <td
                          key={i}
                          className="font-mono"
                          style={{
                            padding: "9px 0",
                            color: i === 0 ? "#eef2f5" : "#aab4bd",
                            borderTop: "1px solid #1c222b",
                          }}
                        >
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          {/* Operating Stack Cost */}
          <SectionCard title="Operating Stack Cost" status="live" statusNote="operating_stack table">
            {stackItems.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No stack items seeded yet. Run the CEO schema migration and seed the operating_stack table.
              </p>
            ) : (
              <>
                {stackItems.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between py-2 min-w-0"
                    style={{ borderTop: "1px solid #1c222b" }}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[12.5px] font-semibold truncate-text" style={{ color: "#eef2f5" }}>
                        {item.service_name}
                      </span>
                      <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
                        {item.category}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <StatusBadge status={item.status} />
                      <span className="text-[12px] font-mono" style={{ color: "#5eead4" }}>
                        ${item.monthly_cost_usd}/mo
                      </span>
                    </div>
                  </div>
                ))}
                <div
                  className="flex items-center justify-between pt-3 mt-1"
                  style={{ borderTop: "2px solid #1c222b" }}
                >
                  <span className="text-[13px] font-bold" style={{ color: "#c7cfd6" }}>Total (active)</span>
                  <span className="text-[13px] font-bold font-mono" style={{ color: "#5eead4" }}>
                    ${totalBurn.toFixed(2)}/mo
                  </span>
                </div>
              </>
            )}
          </SectionCard>

          {/* Exit Gate Tracker */}
          <SectionCard
            title="Exit Gate Tracker — CorVel Acquisition"
            status="not_built"
            statusNote="static mock — no MRR-tracking wiring yet"
            style={{
              background: "radial-gradient(circle at 15% 15%, #6fce8f22, #10201a 70%)",
              border: "1px solid #1f3d2e",
            }}
          >
            <div className="space-y-2 mb-4">
              {EXIT_METRICS.map((m) => (
                <div key={m.label} className="flex items-center justify-between">
                  <span className="text-[12px] font-mono" style={{ color: "#8b96a3" }}>{m.label}</span>
                  <span className="text-[12px] font-mono font-semibold" style={{ color: "#6fce8f" }}>{m.value}</span>
                </div>
              ))}
            </div>
            <ProgressBar value={0} accent="#6fce8f" height={6} />
            <p className="text-[11px] font-mono mt-2" style={{ color: "#5b6673" }}>
              0 / 3 consecutive months at $15K MRR
            </p>
          </SectionCard>

          {/* Finance Agent Roster */}
          <SectionCard title="Finance Agents" status="not_built" statusNote="agent code exists but has never run — static roster, not internal_agent_runs">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              {FINANCE_AGENTS.map((a) => (
                <AgentRosterCard key={a.name} {...a} />
              ))}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
