"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TaskChecklist } from "./TaskChecklist";
import type { BuildQueueItem, BuildTask } from "@/lib/types";

export function ProductBuildCard({ item, tasks, defaultOpen }: { item: BuildQueueItem; tasks: BuildTask[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const percent = tasks.length === 0 ? 0 : Math.round((completedCount / tasks.length) * 100);

  return (
    <div style={{ borderTop: "1px solid #1c2535" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 px-5 py-3 min-w-0 flex-wrap text-left"
        style={{ minHeight: 44 }}
      >
        <span className="text-[13px] font-semibold min-w-0 truncate-text" style={{ color: "#eef2f5" }}>
          {item.product_name}
        </span>
        <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
          {item.vertical}
        </span>
        <div className="flex-1" />
        {tasks.length > 0 && (
          <span className="text-[11px] font-mono shrink-0" style={{ color: "#5eead4" }}>
            {percent}%
          </span>
        )}
        <StatusBadge status={item.status === "launched" ? "completed" : "approved"} pill />
        <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="px-5 pb-4">
          {tasks.length === 0 ? (
            <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>No checklist generated for this build yet.</p>
          ) : (
            <TaskChecklist opportunityId={item.id} initialTasks={tasks} />
          )}
        </div>
      )}
    </div>
  );
}
