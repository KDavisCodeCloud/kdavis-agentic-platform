import Link from "next/link";
import { TeamShell } from "@/components/shell/TeamShell";
import { TopBar } from "@/components/shell/TopBar";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MOCK_TASKS } from "@/lib/types";

export default function TasksPage() {
  const tasks = MOCK_TASKS;

  return (
    <TeamShell>
      <TopBar taskName="My Tasks" />
      <div className="flex-1 overflow-y-auto p-6 pb-20 md:pb-6 min-w-0">
        {tasks.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-[12px] font-mono" style={{ color: "#5b6673" }}>
              No tasks assigned yet
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

            {tasks.map((task, i) => {
              const isActive = task.status === "in_progress";
              const isDone = task.status === "completed" || task.status === "approved";

              return (
                <div
                  key={task.id}
                  className="flex items-center gap-3 px-5 py-3 min-w-0 flex-wrap"
                  style={{
                    borderTop: "1px solid #1c2535",
                    borderLeft: isActive ? "3px solid #5eead4" : "3px solid transparent",
                    opacity: isDone ? 0.5 : 1,
                  }}
                >
                  {/* Product name */}
                  <span
                    className="text-[13px] font-semibold shrink-0 min-w-[100px]"
                    style={{ color: isDone ? "#5b6673" : "#eef2f5" }}
                  >
                    {task.product_name}
                  </span>

                  {/* Task type badge */}
                  <span
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{ backgroundColor: "#111825", color: "#8b96a3", border: "1px solid #1c2535" }}
                  >
                    {task.task_type}
                  </span>

                  {/* Status */}
                  <StatusBadge status={task.status} pill />

                  {/* Priority */}
                  <StatusBadge status={task.priority} />

                  {/* Due date */}
                  <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
                    Due {task.due_date}
                  </span>

                  {/* Progress */}
                  {task.current_step && task.total_steps && (
                    <span className="text-[11px] font-mono shrink-0" style={{ color: "#5b6673" }}>
                      step {task.current_step}/{task.total_steps}
                    </span>
                  )}

                  <div className="flex-1" />

                  {/* Submit button — only on in-progress */}
                  {isActive && (
                    <Link
                      href="/current-task"
                      className="shrink-0 px-3 py-1.5 rounded-[6px] text-[12px] font-semibold transition-opacity hover:opacity-80"
                      style={{
                        border: "1px solid #5eead4",
                        color: "#5eead4",
                        backgroundColor: "transparent",
                      }}
                    >
                      Open Task
                    </Link>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Mobile bottom tab bar */}
      <MobileTabBar active="tasks" />
    </TeamShell>
  );
}

function MobileTabBar({ active }: { active: "tasks" | "current" | "resources" }) {
  const tabs = [
    { label: "My Tasks",     href: "/tasks",        key: "tasks" },
    { label: "Current Task", href: "/current-task", key: "current" },
    { label: "Resources",    href: "/resources",    key: "resources" },
  ];
  return (
    <nav
      className="flex md:hidden shrink-0"
      style={{
        height: "48px",
        backgroundColor: "#0f1520",
        borderTop: "1px solid #1c2535",
      }}
    >
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          className="flex-1 flex items-center justify-center text-[11px] font-semibold transition-colors"
          style={{
            color: active === tab.key ? "#5eead4" : "#5b6673",
            borderTop: active === tab.key ? "2px solid #5eead4" : "2px solid transparent",
          }}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
