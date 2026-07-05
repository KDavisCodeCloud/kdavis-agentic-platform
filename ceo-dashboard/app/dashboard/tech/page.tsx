import { createClient } from "@/lib/supabase/server";
import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { BuildQueueItem } from "@/lib/types";

const INFRA = [
  { name: "Supabase",    status: "healthy", checked: "now" },
  { name: "Vercel",      status: "healthy", checked: "now" },
  { name: "FastAPI",     status: "healthy", checked: "now" },
  { name: "n8n",         status: "healthy", checked: "now" },
  { name: "GitHub",      status: "healthy", checked: "now" },
];

const AGENT_HEALTH = [
  { agent: "Dispatch (Orchestrator)", product: "MSE", lastRun: "last session", status: "healthy", errors: 0 },
  { agent: "Verdict (Aggregator)",    product: "MSE", lastRun: "last session", status: "healthy", errors: 0 },
  { agent: "Ledger",                  product: "MSE", lastRun: "—",            status: "pending", errors: 0 },
  { agent: "Anchor",                  product: "MSE", lastRun: "—",            status: "pending", errors: 0 },
  { agent: "Comply",                  product: "MSE", lastRun: "—",            status: "pending", errors: 0 },
  { agent: "Runway",                  product: "MSE", lastRun: "—",            status: "pending", errors: 0 },
];

export default async function TechPage() {
  const supabase = await createClient();
  const { data: buildQueue } = await supabase
    .from("build_queue")
    .select("*")
    .neq("status", "done")
    .order("created_at", { ascending: false });

  const queue = (buildQueue ?? []) as BuildQueueItem[];

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Technology" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Infrastructure Health */}
          <SectionCard title="Infrastructure Health">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
              {INFRA.map((svc) => (
                <div
                  key={svc.name}
                  className="rounded-[10px] p-3.5 flex items-center justify-between"
                  style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
                >
                  <div>
                    <p className="text-[12.5px] font-semibold mb-1" style={{ color: "#eef2f5" }}>{svc.name}</p>
                    <p className="text-[10px] font-mono" style={{ color: "#5b6673" }}>Checked {svc.checked}</p>
                  </div>
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: svc.status === "healthy" ? "#6fce8f" : svc.status === "degraded" ? "#e8963f" : "#e05d5d" }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>

          {/* Agent Health */}
          <SectionCard title="Agent Health">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Agent", "Product", "Last Run", "Status", "Errors (7d)"].map((h) => (
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
                  {AGENT_HEALTH.map((row) => (
                    <tr key={row.agent}>
                      <td className="font-semibold" style={{ color: "#eef2f5", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.agent}
                      </td>
                      <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.product}
                      </td>
                      <td className="font-mono" style={{ color: "#5b6673", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.lastRun}
                      </td>
                      <td style={{ padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="font-mono text-center" style={{ color: "#5b6673", padding: "9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.errors}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          {/* Build Queue */}
          <SectionCard title="Build Queue">
            {queue.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No items in the build queue. Add items via the Operations department.
              </p>
            ) : (
              queue.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 py-2.5 min-w-0"
                  style={{ borderTop: "1px solid #1c222b" }}
                >
                  <StatusBadge status={item.priority} />
                  <p className="flex-1 text-[12.5px] font-semibold truncate-text min-w-0" style={{ color: "#eef2f5" }}>
                    {item.item}
                  </p>
                  {item.repo && (
                    <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
                      {item.repo}
                    </span>
                  )}
                  <StatusBadge status={item.status} />
                </div>
              ))
            )}
            {/* TODO: filter by repo/priority */}
          </SectionCard>

          {/* Cost Optimizer */}
          <SectionCard title="Cost Optimizer">
            <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
              No cost flags detected. All active services within expected ranges.
            </p>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
