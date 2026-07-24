import { createClient } from "@/lib/supabase/server";
import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { TeamMember } from "@/lib/types";

const ONBOARDING_STEPS = [
  "Send magic link invite",
  "Assign role in user_metadata",
  "Scope department access",
  "Verify RLS policy enforces access",
  "Confirm login and permissions",
];

const ROUTING_RULES = [
  { action: "Deploy to production",    routes_to: "Kelvin" },
  { action: "Publish marketing content", routes_to: "Wife" },
  { action: "Approve legal document",  routes_to: "Kelvin" },
  { action: "Review code PR",          routes_to: "Son (read-only)" },
  { action: "Send cold outreach",      routes_to: "Wife" },
];

export default async function HrPage() {
  const supabase = await createClient();
  const { data: members } = await supabase
    .from("team_members")
    .select("*")
    .order("created_at");

  const team = (members ?? []) as TeamMember[];

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="HR" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Team Roster */}
          <SectionCard title="Team Roster" status="live" statusNote="team_members table">
            {team.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No team members seeded yet. Run the CEO schema migration and insert team_members rows.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["Name", "Role", "Dept Access", "Permission", "Last Active"].map((h) => (
                        <th
                          key={h}
                          className="text-left font-mono font-semibold"
                          style={{ color: "#5b6673", borderBottom: "1px solid #1c222b", paddingBottom: "8px", paddingRight: "16px" }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {team.map((m) => (
                      <tr key={m.id}>
                        <td className="font-semibold" style={{ color: "#eef2f5", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                          {m.name}
                        </td>
                        <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                          {m.role}
                        </td>
                        <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                          {m.department_access.join(", ")}
                        </td>
                        <td style={{ padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                          <StatusBadge status={m.permission_level} />
                        </td>
                        <td className="font-mono" style={{ color: "#5b6673", padding: "9px 0", borderTop: "1px solid #1c222b" }}>
                          {m.last_active_at ? new Date(m.last_active_at).toLocaleDateString() : "Never"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {/* Onboarding Flow */}
          <SectionCard title="Onboarding Flow" status="not_built" statusNote="static checklist — no onboarding_steps table exists yet">
            {ONBOARDING_STEPS.map((step, i) => (
              <div
                key={i}
                className="flex items-center gap-3 py-2.5"
                style={{ borderTop: i > 0 ? "1px solid #1c222b" : "none" }}
              >
                <span
                  className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold"
                  style={{ backgroundColor: "#5eead41a", color: "#5eead4" }}
                >
                  {i + 1}
                </span>
                <span className="text-[12.5px]" style={{ color: "#eef2f5" }}>{step}</span>
              </div>
            ))}
          </SectionCard>

          {/* HITL Routing Rules */}
          <SectionCard title="HITL Routing Rules" status="not_built" statusNote="static list — hitl_routing_rules table exists but is empty, not queried here">
            {ROUTING_RULES.map((rule, i) => (
              <div
                key={i}
                className="flex items-center justify-between py-2.5 min-w-0"
                style={{ borderTop: i > 0 ? "1px solid #1c222b" : "none" }}
              >
                <span className="text-[12px] truncate-text min-w-0" style={{ color: "#aab4bd" }}>
                  {rule.action}
                </span>
                <span className="text-[12px] font-semibold shrink-0 ml-3" style={{ color: "#5eead4" }}>
                  → {rule.routes_to}
                </span>
              </div>
            ))}
          </SectionCard>

          {/* Approval Chain */}
          <SectionCard title="Approval Chain" status="not_built" statusNote="static org diagram, not derived from team_members' real roles">
            <div className="flex flex-col items-center gap-3 py-2">
              <div className="rounded-[8px] px-4 py-2 text-center" style={{ backgroundColor: "#5eead41a", border: "1px solid #5eead4" }}>
                <p className="text-[13px] font-bold" style={{ color: "#5eead4" }}>Kelvin</p>
                <p className="text-[10px] font-mono" style={{ color: "#5b6673" }}>Full Access</p>
              </div>
              <div className="w-px h-5" style={{ backgroundColor: "#1c222b" }} />
              <div className="flex gap-8">
                <div className="rounded-[8px] px-4 py-2 text-center" style={{ backgroundColor: "#6fce8f22", border: "1px solid #6fce8f" }}>
                  <p className="text-[13px] font-bold" style={{ color: "#6fce8f" }}>Wife</p>
                  <p className="text-[10px] font-mono" style={{ color: "#5b6673" }}>Marketing / Ops / HR</p>
                </div>
                <div className="rounded-[8px] px-4 py-2 text-center" style={{ backgroundColor: "#7ea6f522", border: "1px solid #7ea6f5" }}>
                  <p className="text-[13px] font-bold" style={{ color: "#7ea6f5" }}>Son</p>
                  <p className="text-[10px] font-mono" style={{ color: "#5b6673" }}>R&amp;D / Tech (read-only)</p>
                </div>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
