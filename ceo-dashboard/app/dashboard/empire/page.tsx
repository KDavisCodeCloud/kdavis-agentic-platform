import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { HitlResolveForm } from "@/components/ui/HitlResolveForm";

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_API_URL || "http://localhost:8001";

interface OrchestratorHitl {
  id: string;
  product: string;
  issue: string;
  stop_reason: string;
  resolution: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
}

interface OrchestratorTask {
  id: string;
  product: string;
  agent_target: string;
  status: string;
  created_at: string;
}

interface OrchestratorAgent {
  id: string;
  name: string;
  product: string;
  status: string;
  last_seen_at: string | null;
}

async function fetchOrchestrator<T>(path: string): Promise<{ data: T | null; error: string | null }> {
  try {
    const res = await fetch(`${ORCHESTRATOR_URL}${path}`, { cache: "no-store" });
    if (!res.ok) return { data: null, error: `${res.status} ${await res.text().catch(() => "")}` };
    return { data: (await res.json()) as T, error: null };
  } catch (err) {
    return { data: null, error: err instanceof Error ? err.message : "Could not reach the Orchestrator." };
  }
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default async function EmpirePage() {
  const [hitl, tasks, agents] = await Promise.all([
    fetchOrchestrator<OrchestratorHitl[]>("/hitl"),
    fetchOrchestrator<OrchestratorTask[]>("/tasks"),
    fetchOrchestrator<OrchestratorAgent[]>("/agents"),
  ]);

  const openHitl = (hitl.data ?? []).filter((t) => !t.resolved_at);
  const resolvedHitl = (hitl.data ?? []).filter((t) => t.resolved_at).slice(0, 10);

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Decoded Empire" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* HITL Queue -- decoded-empire-orchestrator's real approval
              queue (NOVA/Apollo/Ledger/Counsel), not the separate internal
              hitl_queue table this dashboard's own commercial agents use
              (see HITLQueuePanel.tsx) -- deliberately kept distinct, two
              different systems with two different agent rosters. */}
          <SectionCard
            title="HITL Queue"
            status={hitl.error ? "not_built" : "live"}
            statusNote={hitl.error ?? "decoded-empire-orchestrator, Railway"}
          >
            {hitl.error ? (
              <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>{hitl.error}</p>
            ) : openHitl.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>No open HITL tickets.</p>
            ) : (
              <div className="space-y-3">
                {openHitl.map((t) => (
                  <div key={t.id} className="pb-3" style={{ borderBottom: "1px solid #1c222b" }}>
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <span className="text-[12.5px] font-semibold" style={{ color: "#eef2f5" }}>{t.product}</span>
                      <StatusBadge status={t.stop_reason} />
                      <span className="text-[10px] font-mono ml-auto" style={{ color: "#5b6673" }}>{timeAgo(t.created_at)}</span>
                    </div>
                    <p className="text-[12px]" style={{ color: "#aab4bd" }}>{t.issue}</p>
                    <HitlResolveForm ticketId={t.id} />
                  </div>
                ))}
              </div>
            )}

            {resolvedHitl.length > 0 && (
              <>
                <p className="text-[11px] font-mono mt-4 mb-2" style={{ color: "#5b6673" }}>
                  Recently resolved ({resolvedHitl.length})
                </p>
                <div className="space-y-2">
                  {resolvedHitl.map((t) => (
                    <div key={t.id} className="flex items-center gap-2 text-[11px] font-mono" style={{ color: "#5b6673" }}>
                      <StatusBadge status="approved" />
                      <span className="truncate-text">{t.product}: {t.resolution}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </SectionCard>

          {/* Tasks */}
          <SectionCard
            title="Tasks"
            status={tasks.error ? "not_built" : "live"}
            statusNote={tasks.error ?? "decoded-empire-orchestrator, Railway"}
          >
            {tasks.error ? (
              <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>{tasks.error}</p>
            ) : (tasks.data ?? []).length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>No tasks recorded.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["Product", "Agent", "Status", "Created"].map((h) => (
                        <th key={h} className="text-left font-mono font-semibold" style={{ color: "#5b6673", borderBottom: "1px solid #1c222b", paddingBottom: "8px", paddingRight: "16px" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(tasks.data ?? []).slice(0, 20).map((t) => (
                      <tr key={t.id}>
                        <td className="font-semibold" style={{ color: "#eef2f5", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>{t.product}</td>
                        <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>{t.agent_target}</td>
                        <td style={{ padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}><StatusBadge status={t.status} /></td>
                        <td className="font-mono" style={{ color: "#5b6673", padding: "9px 0", borderTop: "1px solid #1c222b" }}>{timeAgo(t.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {/* Agents */}
          <SectionCard
            title="Agent Registry"
            status={agents.error ? "not_built" : "live"}
            statusNote={agents.error ?? "decoded-empire-orchestrator, Railway"}
          >
            {agents.error ? (
              <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>{agents.error}</p>
            ) : (agents.data ?? []).length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>No agents registered.</p>
            ) : (
              (agents.data ?? []).map((a) => (
                <div key={a.id} className="flex items-center gap-3 py-2.5" style={{ borderTop: "1px solid #1c222b" }}>
                  <span className="text-[12.5px] font-semibold" style={{ color: "#eef2f5" }}>{a.name}</span>
                  <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>{a.product}</span>
                  <StatusBadge status={a.status} />
                  <span className="text-[10px] font-mono ml-auto" style={{ color: "#5b6673" }}>{timeAgo(a.last_seen_at)}</span>
                </div>
              ))
            )}
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
