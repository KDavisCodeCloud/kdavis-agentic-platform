import { TeamShell } from "@/components/shell/TeamShell";
import { TopBar } from "@/components/shell/TopBar";
import { MobileTabBar } from "@/components/shell/MobileTabBar";
import { ProductBuildCard } from "@/components/build/ProductBuildCard";
import { createAdminClient } from "@/lib/supabase/admin";
import type { BuildQueueItem, BuildTask } from "@/lib/types";

// Same reasoning as build-queue/page.tsx: without this, Next.js prerenders
// this at build time and it never reflects anything that happens after.
export const dynamic = "force-dynamic";

// "My Tasks" used to be a hardcoded MOCK_TASKS array (FreightAudit,
// LeadSequencer -- products that were never real). Replaced with the real
// build_tasks data: every currently-queued product that still has at
// least one incomplete task, same checklist component as Build Queue
// (mark complete + notes), just pre-expanded and filtered to what's
// actually actionable right now rather than showing 100%-done products.
async function getMyTasksData(): Promise<{ items: BuildQueueItem[]; tasksByOpportunity: Map<string, BuildTask[]> }> {
  const supabase = createAdminClient();

  const { data: opportunities } = await supabase
    .from("opportunity_pipeline")
    .select("id, solution_concept, vertical, status, human_review_status")
    .in("status", ["READY_TO_BUILD", "building"])
    .eq("human_review_status", "approved")
    .order("created_at", { ascending: false });

  const { data: briefs } = await supabase.from("mse_build_briefs").select("opportunity_id, product_name");
  const briefNameByOpportunityId = new Map(
    (briefs ?? []).filter((b) => b.opportunity_id).map((b) => [b.opportunity_id as string, b.product_name as string])
  );

  const rows = (opportunities ?? []) as { id: string; solution_concept: string; vertical: string }[];
  const ids = rows.map((r) => r.id);

  const tasksByOpportunity = new Map<string, BuildTask[]>();
  if (ids.length > 0) {
    const { data: tasks } = await supabase
      .from("build_tasks")
      .select("id, opportunity_id, task_type, title, description, sort_order, status, notes, completed_by, completed_at")
      .in("opportunity_id", ids)
      .order("sort_order", { ascending: true });
    for (const t of (tasks ?? []) as BuildTask[]) {
      const list = tasksByOpportunity.get(t.opportunity_id) ?? [];
      list.push(t);
      tasksByOpportunity.set(t.opportunity_id, list);
    }
  }

  // Only products with at least one task still not done -- a fully
  // completed product belongs on Build Queue's history, not "what's left."
  const items = rows
    .filter((r) => (tasksByOpportunity.get(r.id) ?? []).some((t) => t.status !== "completed"))
    .map((r): BuildQueueItem => ({
      id: r.id,
      product_name: briefNameByOpportunityId.get(r.id) ?? r.solution_concept,
      vertical: r.vertical,
      has_brief: briefNameByOpportunityId.has(r.id),
      status: "queued",
    }));

  return { items, tasksByOpportunity };
}

export default async function TasksPage() {
  const { items, tasksByOpportunity } = await getMyTasksData();

  return (
    <TeamShell>
      <TopBar taskName="My Tasks" />
      <div className="flex-1 overflow-y-auto p-6 pb-20 md:pb-6 min-w-0">
        {items.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-[12px] font-mono" style={{ color: "#5b6673" }}>
              Nothing left to do — every queued build is fully checked off.
            </p>
          </div>
        ) : (
          <div
            className="rounded-[14px] overflow-hidden"
            style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}
          >
            <div className="px-5 pt-5 pb-3">
              <p className="text-[13px] font-bold tracking-wide" style={{ color: "#c7cfd6" }}>
                MY TASKS
              </p>
            </div>

            {items.map((item) => (
              <ProductBuildCard
                key={item.id}
                item={item}
                tasks={tasksByOpportunity.get(item.id) ?? []}
                defaultOpen
              />
            ))}
          </div>
        )}
      </div>

      <MobileTabBar active="tasks" />
    </TeamShell>
  );
}
