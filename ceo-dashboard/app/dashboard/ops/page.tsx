import { createClient } from "@/lib/supabase/server";
import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { FireButton } from "@/components/ui/FireButton";
import type { SessionLogEntry, GapItem } from "@/lib/types";

// Known issue: api/routes/agents.py only recognizes agent_01-10 prefixes
// (e.g. "agent_01_cicd_triage"). These short IDs will 400 against today's
// backend — built to spec anyway, per Session 15 instructions.
const OPS_AGENTS = [
  { agentId: "cicd_triage",     label: "CI/CD Triage" },
  { agentId: "k8s_alert",       label: "K8s Alert Scan" },
  { agentId: "pr_review",       label: "PR Review" },
  { agentId: "drift_detection", label: "Drift Detection" },
];

const BUILD_ORDER_ITEMS = [
  { label: "GAP 1 — API foundation + events router", done: true },
  { label: "GAP 2 — Supabase core schema (tenants, usage_events)", done: true },
  { label: "GAP 3 — Config + environment setup", done: true },
  { label: "GAP 4 — Stripe webhook router", done: true },
  { label: "GAP 5 — n8n self-hosted setup", done: true },
  { label: "GAP 6 — n8n weekly digest workflow", done: true },
  { label: "GAP 7 — n8n retention sequences workflow", done: true },
  { label: "GAP 8 — Resend email integration", done: true },
  { label: "GAP 9 — Opportunity pipeline migration", done: true },
  { label: "GAP 10 — RLS auth.uid() migration", done: true },
  { label: "GAP 11 — Supabase client (admin vs. per-request)", done: true },
  { label: "GAP 12 — Legal docs", done: true },
  { label: "GAP 13 — Agent cadence (orchestrator + aggregator)", done: true },
  { label: "CEO Decoded dashboard", done: false },
  { label: "MSE dashboard", done: false },
  { label: "Week 2 agent: Market sizing vertical intel", done: false },
];

const WEEKLY_RHYTHM = [
  { day: "Mon", type: "Architecture",  items: 2 },
  { day: "Tue", type: "Build Sprint",  items: 3 },
  { day: "Wed", type: "Build Sprint",  items: 3 },
  { day: "Thu", type: "Agent Cadence", items: 1 },
  { day: "Fri", type: "Review",        items: 2 },
  { day: "Sat", type: "Deploy / Push", items: 1 },
  { day: "Sun", type: "Rest",          items: 0 },
];

export default async function OpsPage() {
  const supabase = await createClient();

  const [{ data: sessionLog }, { data: gaps }] = await Promise.all([
    supabase
      .from("session_log")
      .select("*")
      .order("session_date", { ascending: false })
      .limit(10),
    supabase
      .from("gap_tracker")
      .select("*")
      .order("created_at", { ascending: false }),
  ]);

  const sessions = (sessionLog ?? []) as SessionLogEntry[];
  const gapItems = (gaps ?? []) as GapItem[];

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Operations" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Agent Triggers */}
          <SectionCard title="Agent Triggers">
            <div className="flex flex-wrap gap-2">
              {OPS_AGENTS.map((a) => (
                <FireButton key={a.agentId} agentId={a.agentId} label={a.label} payload={{}} />
              ))}
            </div>
          </SectionCard>

          {/* Build Order tracker */}
          <SectionCard title="Build Order">
            <div className="space-y-0">
              {BUILD_ORDER_ITEMS.map((item, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 py-2.5 min-w-0"
                  style={{ borderTop: i > 0 ? "1px solid #1c222b" : "none" }}
                >
                  <span
                    className="shrink-0 w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold"
                    style={{
                      border: `1.5px solid ${item.done ? "#6fce8f" : "#3a4250"}`,
                      color: item.done ? "#6fce8f" : "#3a4250",
                    }}
                  >
                    {item.done ? "✓" : ""}
                  </span>
                  <span
                    className="text-[12.5px]"
                    style={{ color: item.done ? "#5b6673" : "#eef2f5", textDecoration: item.done ? "line-through" : "none" }}
                  >
                    {item.label}
                  </span>
                </div>
              ))}
            </div>
          </SectionCard>

          {/* Weekly Rhythm */}
          <SectionCard title="Weekly Rhythm">
            <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(7, 1fr)" }}>
              {WEEKLY_RHYTHM.map((day) => (
                <div
                  key={day.day}
                  className="rounded-[8px] p-2.5 text-center"
                  style={{
                    backgroundColor: day.day === "Sun" ? "#0d1117" : "#10151b",
                    border: "1px solid #1c222b",
                    opacity: day.day === "Sun" ? 0.45 : 1,
                  }}
                >
                  <p className="text-[11px] font-mono font-semibold mb-1" style={{ color: "#8b96a3" }}>
                    {day.day}
                  </p>
                  <p className="text-[10px] font-mono" style={{ color: day.day === "Sun" ? "#3a4250" : "#eef2f5" }}>
                    {day.type}
                  </p>
                  {day.day !== "Sun" && day.items > 0 && (
                    <p className="text-[10px] font-mono mt-1" style={{ color: "#5b6673" }}>
                      {day.items} open
                    </p>
                  )}
                </div>
              ))}
            </div>
          </SectionCard>

          {/* GAP Tracker */}
          <SectionCard title="GAP Tracker">
            {gapItems.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No gaps tracked yet. Seed the gap_tracker table from the migration.
              </p>
            ) : (
              gapItems.map((gap) => (
                <div
                  key={gap.id}
                  className="flex items-center justify-between py-2.5 min-w-0"
                  style={{ borderTop: "1px solid #1c222b" }}
                >
                  <div className="min-w-0">
                    <p className="text-[12.5px] font-semibold truncate-text" style={{ color: "#eef2f5" }}>
                      {gap.gap_name}
                    </p>
                    {gap.product && (
                      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>{gap.product}</p>
                    )}
                  </div>
                  <StatusBadge status={gap.status} />
                </div>
              ))
            )}
          </SectionCard>

          {/* Session Log (append-only) */}
          <SectionCard title="Session Log">
            {sessions.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No sessions logged yet.
              </p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.id}
                  className="py-2.5 min-w-0"
                  style={{ borderTop: "1px solid #1c222b" }}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                      {s.session_date}
                    </span>
                    {s.product && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                        style={{ backgroundColor: "#5eead41a", color: "#5eead4" }}>
                        {s.product}
                      </span>
                    )}
                  </div>
                  <p className="text-[12px]" style={{ color: "#aab4bd" }}>{s.summary}</p>
                </div>
              ))
            )}
            {/* No delete affordance — append-only by design */}
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
