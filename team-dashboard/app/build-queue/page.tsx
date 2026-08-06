import { TeamShell } from "@/components/shell/TeamShell";
import { TopBar } from "@/components/shell/TopBar";
import { MobileTabBar } from "@/components/shell/MobileTabBar";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { createAdminClient } from "@/lib/supabase/admin";
import type { BuildQueueItem } from "@/lib/types";

// Without this, Next.js sees no per-request API (cookies(), headers()) used
// directly in this Server Component and prerenders it once at build time --
// the whole point here is showing what's current, so a build-time-frozen
// snapshot would silently go stale the moment anything in the pipeline
// changes. Same fix applied to decoded-six's sitemap.ts for the same reason.
export const dynamic = "force-dynamic";

// "Build Queue" here matches the exact same definition the MSE dashboard's
// own Build Queue tab uses (kdavis-microsaas-engine/frontend/app/pipeline/
// page.tsx, fixed 2026-08-03): human_review_status = 'approved'. Not
// status = 'READY_TO_BUILD' alone -- that's Verdict's own pass/fail before
// a human ever reviewed it, so using it here would show unreviewed
// opportunities as if they were queued to build.
async function getBuildQueueData(): Promise<{ queued: BuildQueueItem[]; launched: BuildQueueItem[] }> {
  const supabase = createAdminClient();

  const { data: opportunities } = await supabase
    .from("opportunity_pipeline")
    .select("id, solution_concept, vertical, status, human_review_status")
    .in("status", ["READY_TO_BUILD", "launched", "building"])
    .order("created_at", { ascending: false });

  const { data: briefs } = await supabase
    .from("mse_build_briefs")
    .select("opportunity_id, product_name");

  const briefNameByOpportunityId = new Map(
    (briefs ?? []).filter((b) => b.opportunity_id).map((b) => [b.opportunity_id as string, b.product_name as string])
  );

  const rows = (opportunities ?? []) as {
    id: string; solution_concept: string; vertical: string;
    status: string; human_review_status: string;
  }[];

  const toItem = (o: (typeof rows)[number]): BuildQueueItem => ({
    id: o.id,
    product_name: briefNameByOpportunityId.get(o.id) ?? o.solution_concept,
    vertical: o.vertical,
    has_brief: briefNameByOpportunityId.has(o.id),
    status: o.status === "launched" ? "launched" : "queued",
  });

  const queued = rows.filter((o) => o.status !== "launched" && o.human_review_status === "approved").map(toItem);
  const launched = rows.filter((o) => o.status === "launched").map(toItem);

  return { queued, launched };
}

export default async function BuildQueuePage() {
  const { queued, launched } = await getBuildQueueData();

  return (
    <TeamShell>
      <TopBar taskName="Build Queue" />
      <div className="flex-1 overflow-y-auto p-6 pb-20 md:pb-6 min-w-0 space-y-5">
        <Section title="IN BUILD QUEUE" items={queued} emptyText="Nothing approved and queued to build right now." />
        <Section title="COMPLETED" items={launched} emptyText="Nothing has shipped yet." />
      </div>

      <MobileTabBar active="build-queue" />
    </TeamShell>
  );
}

function Section({ title, items, emptyText }: { title: string; items: BuildQueueItem[]; emptyText: string }) {
  return (
    <div className="rounded-[14px] overflow-hidden" style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}>
      <div className="px-5 pt-5 pb-3 flex items-center justify-between">
        <p className="text-[13px] font-bold tracking-wide" style={{ color: "#c7cfd6" }}>
          {title}
        </p>
        <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          {items.length}
        </span>
      </div>

      {items.length === 0 ? (
        <p className="px-5 pb-5 text-[12px] font-mono" style={{ color: "#5b6673" }}>
          {emptyText}
        </p>
      ) : (
        items.map((item, i) => (
          <div
            key={item.id}
            className="flex items-center gap-3 px-5 py-3 min-w-0 flex-wrap"
            style={{ borderTop: i > 0 ? "1px solid #1c2535" : "none" }}
          >
            <span className="text-[13px] font-semibold min-w-0 truncate-text" style={{ color: "#eef2f5" }}>
              {item.product_name}
            </span>
            <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
              {item.vertical}
            </span>
            <div className="flex-1" />
            {!item.has_brief && item.status === "queued" && (
              <span className="text-[10.5px] font-mono shrink-0" style={{ color: "#e8963f" }}>
                brief not generated yet
              </span>
            )}
            <StatusBadge status={item.status === "launched" ? "completed" : "approved"} pill />
          </div>
        ))
      )}
    </div>
  );
}
