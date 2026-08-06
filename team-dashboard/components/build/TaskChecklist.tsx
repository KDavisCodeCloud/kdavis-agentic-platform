"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { BuildTask } from "@/lib/types";

// Writes go through the team member's own session (RLS: build_tasks is
// "authenticated" read/write, not admin-only like opportunity_pipeline
// itself — see migration 20260806000019's comment for why that split is
// safe). Subscribes to Realtime on this product's own tasks so a change
// made in the MSE dashboard or by another team member shows up here
// without a refresh, and vice versa — "real time" isn't just "freshly
// fetched on page load."
export function TaskChecklist({ opportunityId, initialTasks }: { opportunityId: string; initialTasks: BuildTask[] }) {
  const supabase = createClient();
  const [tasks, setTasks] = useState<BuildTask[]>(initialTasks);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

  useEffect(() => {
    const channel = supabase
      .channel(`build_tasks:${opportunityId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "build_tasks", filter: `opportunity_id=eq.${opportunityId}` },
        (payload) => {
          setTasks((prev) => {
            if (payload.eventType === "DELETE") {
              return prev.filter((t) => t.id !== (payload.old as BuildTask).id);
            }
            const updated = payload.new as BuildTask;
            const exists = prev.some((t) => t.id === updated.id);
            return exists ? prev.map((t) => (t.id === updated.id ? updated : t)) : [...prev, updated].sort((a, b) => a.sort_order - b.sort_order);
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opportunityId]);

  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const percent = tasks.length === 0 ? 0 : Math.round((completedCount / tasks.length) * 100);

  async function toggleComplete(task: BuildTask) {
    const nextStatus = task.status === "completed" ? "pending" : "completed";
    setSavingId(task.id);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      const { error } = await supabase
        .from("build_tasks")
        .update({
          status: nextStatus,
          completed_by: nextStatus === "completed" ? (user?.email ?? "unknown") : null,
          completed_at: nextStatus === "completed" ? new Date().toISOString() : null,
          updated_at: new Date().toISOString(),
        })
        .eq("id", task.id);
      if (error) throw error;
      // Optimistic local update -- the Realtime event above will also land
      // and reconcile, but this makes the checkbox feel instant rather
      // than waiting a round trip.
      setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, status: nextStatus } : t)));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to update task");
    } finally {
      setSavingId(null);
    }
  }

  async function saveNote(task: BuildTask) {
    const note = noteDrafts[task.id];
    if (note === undefined) return;
    setSavingId(task.id);
    try {
      const { error } = await supabase
        .from("build_tasks")
        .update({ notes: note, updated_at: new Date().toISOString() })
        .eq("id", task.id);
      if (error) throw error;
      setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, notes: note } : t)));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to save note");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <div className="flex-1 rounded-full" style={{ height: "6px", backgroundColor: "#1c2535" }}>
          <div className="h-full rounded-full transition-all" style={{ width: `${percent}%`, backgroundColor: "#5eead4" }} />
        </div>
        <span className="text-[11px] font-mono shrink-0" style={{ color: "#5eead4" }}>
          {percent}% · {completedCount}/{tasks.length}
        </span>
      </div>

      <div className="space-y-1">
        {tasks.map((task) => {
          const isDone = task.status === "completed";
          const isExpanded = expandedId === task.id;
          return (
            <div key={task.id} className="rounded-[8px]" style={{ backgroundColor: "#111825" }}>
              <div className="flex items-center gap-2.5 px-3 py-2.5 min-w-0">
                <button
                  onClick={() => toggleComplete(task)}
                  disabled={savingId === task.id}
                  className="shrink-0 flex items-center justify-center rounded-[4px] transition-colors"
                  style={{
                    width: "20px", height: "20px",
                    border: `1.5px solid ${isDone ? "#5eead4" : "#3a4250"}`,
                    backgroundColor: isDone ? "#5eead4" : "transparent",
                    opacity: savingId === task.id ? 0.5 : 1,
                  }}
                  aria-label={isDone ? "Mark incomplete" : "Mark complete"}
                >
                  {isDone && <span style={{ color: "#0d1117", fontSize: "12px", fontWeight: 700 }}>✓</span>}
                </button>

                <span
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                  style={{ backgroundColor: "#0d1117", color: "#8b96a3", border: "1px solid #1c2535" }}
                >
                  {task.task_type}
                </span>

                <span
                  className="text-[12.5px] min-w-0 truncate-text flex-1"
                  style={{ color: isDone ? "#5b6673" : "#eef2f5", textDecoration: isDone ? "line-through" : "none" }}
                >
                  {task.title}
                </span>

                {isDone && task.completed_by && (
                  <span className="text-[10.5px] font-mono shrink-0 hidden sm:inline" style={{ color: "#5b6673" }}>
                    {task.completed_by}
                  </span>
                )}

                <button
                  onClick={() => {
                    setExpandedId(isExpanded ? null : task.id);
                    if (noteDrafts[task.id] === undefined) {
                      setNoteDrafts((d) => ({ ...d, [task.id]: task.notes ?? "" }));
                    }
                  }}
                  className="shrink-0 text-[11px] font-mono transition-colors"
                  style={{ color: "#8b96a3", minHeight: 32, minWidth: 32 }}
                >
                  {isExpanded ? "▲" : "▼"}
                </button>
              </div>

              {isExpanded && (
                <div className="px-3 pb-3 space-y-2">
                  <textarea
                    value={noteDrafts[task.id] ?? task.notes ?? ""}
                    onChange={(e) => setNoteDrafts((d) => ({ ...d, [task.id]: e.target.value }))}
                    placeholder="What was done, or notes for whoever picks this up next…"
                    rows={2}
                    className="w-full px-2.5 py-2 rounded-[6px] text-[12px] outline-none resize-none"
                    style={{ backgroundColor: "#0d1117", border: "1px solid #1c2535", color: "#eef2f5", fontSize: 16, minHeight: 44 }}
                  />
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => saveNote(task)}
                      disabled={savingId === task.id}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold"
                      style={{ border: "1px solid #7ea6f5", color: "#7ea6f5", backgroundColor: "transparent", minHeight: 44 }}
                    >
                      Save note
                    </button>
                    {isDone && task.completed_at && (
                      <span className="text-[10.5px] font-mono" style={{ color: "#5b6673" }}>
                        completed {new Date(task.completed_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
