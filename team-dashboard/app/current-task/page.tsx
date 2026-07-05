"use client";
import Link from "next/link";
import { useState } from "react";
import { TeamShell } from "@/components/shell/TeamShell";
import { TopBar } from "@/components/shell/TopBar";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MOCK_TASKS, MOCK_STEPS, MOCK_FILES, type FileRequirement } from "@/lib/types";

export default function CurrentTaskPage() {
  const task = MOCK_TASKS[0];
  const [files, setFiles] = useState<FileRequirement[]>(MOCK_FILES);
  const [notes, setNotes] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const allChecked = files.every((f) => f.checked);

  function toggleFile(i: number) {
    setFiles((prev) => prev.map((f, idx) => idx === i ? { ...f, checked: !f.checked } : f));
  }

  function handleSubmit() {
    if (!allChecked) return;
    setSubmitted(true);
  }

  if (submitted) {
    return (
      <TeamShell>
        <TopBar taskName={task.product_name} status="submitted" />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-[15px] font-semibold mb-2" style={{ color: "#eef2f5" }}>
              Submitted for review
            </p>
            <p className="text-[12px]" style={{ color: "#aab4bd" }}>
              You&apos;ll be notified when it&apos;s approved.
            </p>
            <Link
              href="/tasks"
              className="inline-block mt-4 text-[12px] font-semibold"
              style={{ color: "#5eead4" }}
            >
              Back to My Tasks
            </Link>
          </div>
        </div>
        <MobileTabBar active="current" />
      </TeamShell>
    );
  }

  return (
    <TeamShell>
      <TopBar taskName={task.product_name} status={task.status} />
      <div className="flex-1 overflow-y-auto min-w-0" style={{ paddingBottom: "120px" }}>
        <div className="p-6 space-y-4">
          {/* Task header card */}
          <div
            className="rounded-[14px] p-[18px]"
            style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}
          >
            <p className="text-[15px] font-bold mb-1.5" style={{ color: "#eef2f5" }}>
              {task.title}
            </p>
            <StatusBadge status={task.task_type.toLowerCase().replace(" ", "_")} />
            <p className="text-[11px] font-mono mt-2" style={{ color: "#5b6673" }}>
              Assigned · Due in {task.due_date}
            </p>
            {task.description && (
              <p className="text-[12px] mt-2" style={{ color: "#aab4bd" }}>
                {task.description}
              </p>
            )}
          </div>

          {/* Step list */}
          <div
            className="rounded-[14px] p-5"
            style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}
          >
            <p className="text-[13px] font-bold mb-4" style={{ color: "#c7cfd6" }}>
              TASK STEPS
            </p>
            {MOCK_STEPS.map((step, i) => {
              const isCurrent = step.status === "current";
              const isDone = step.status === "completed";
              return (
                <div
                  key={step.step_number}
                  className="flex items-start gap-3 py-2.5 min-w-0"
                  style={{ borderTop: i > 0 ? "1px solid #1c2535" : "none" }}
                >
                  {/* Step circle */}
                  <div
                    className="shrink-0 w-5 h-5 rounded flex items-center justify-center text-[10px] font-mono font-bold"
                    style={{
                      backgroundColor: isCurrent ? "#5eead4" : isDone ? "#6fce8f22" : "#111825",
                      color: isCurrent ? "#0d1117" : isDone ? "#6fce8f" : "#5b6673",
                      border: isDone ? "1px solid #6fce8f44" : "none",
                    }}
                  >
                    {isDone ? "✓" : step.step_number}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p
                      className="text-[13px] font-semibold"
                      style={{ color: isDone ? "#5b6673" : "#eef2f5" }}
                    >
                      {step.title}
                    </p>
                    <p className="text-[12px]" style={{ color: isDone ? "#5b6673" : "#aab4bd" }}>
                      {step.description}
                    </p>
                  </div>
                  {/* Status pill */}
                  {isCurrent && (
                    <span
                      className="shrink-0 text-[10px] font-mono px-1.5 py-0.5 rounded-[20px]"
                      style={{ backgroundColor: "#5eead422", color: "#5eead4" }}
                    >
                      current
                    </span>
                  )}
                  {isDone && (
                    <span
                      className="shrink-0 text-[10px] font-mono px-1.5 py-0.5 rounded-[20px]"
                      style={{ backgroundColor: "#6fce8f22", color: "#6fce8f" }}
                    >
                      done
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* File checklist */}
          <div
            className="rounded-[14px] p-5"
            style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}
          >
            <p className="text-[13px] font-bold mb-4" style={{ color: "#c7cfd6" }}>
              FILES REQUIRED BEFORE SUBMITTING
            </p>
            {files.map((file, i) => (
              <div
                key={file.filename}
                className="flex items-center gap-3 py-2.5 min-w-0"
                style={{ borderTop: i > 0 ? "1px solid #1c2535" : "none" }}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-semibold" style={{ color: "#eef2f5" }}>
                    {file.filename}
                  </p>
                  <p className="text-[11px] font-mono truncate-text" style={{ color: "#5b6673" }}>
                    {file.path}
                  </p>
                </div>
                {/* Checkbox — 44px min tap target wrapper */}
                <button
                  onClick={() => toggleFile(i)}
                  className="shrink-0 flex items-center justify-center"
                  style={{ width: "44px", height: "44px" }}
                >
                  <div
                    style={{
                      width: "16px",
                      height: "16px",
                      borderRadius: "4px",
                      border: file.checked ? "none" : "1.5px solid #1c2535",
                      backgroundColor: file.checked ? "#5eead4" : "transparent",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "10px",
                      color: "#0d1117",
                      fontWeight: "bold",
                    }}
                  >
                    {file.checked && "✓"}
                  </div>
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Submit section — sticky bottom */}
        <div
          className="fixed bottom-12 md:bottom-0 left-0 right-0 p-4 md:p-6"
          style={{ backgroundColor: "#0d1117", borderTop: "1px solid #1c2535" }}
        >
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Anything unusual to note?"
            rows={2}
            className="w-full rounded-[10px] px-3 py-3 text-[12.5px] outline-none resize-none mb-3"
            style={{
              backgroundColor: "#111825",
              border: "1px solid #1c2535",
              color: "#aab4bd",
            }}
          />
          <button
            onClick={handleSubmit}
            disabled={!allChecked}
            className="w-full h-12 rounded-[10px] text-[13px] font-bold transition-all"
            style={{
              backgroundColor: allChecked ? "#5eead4" : "#1c2535",
              color: allChecked ? "#0d1117" : "#5b6673",
              cursor: allChecked ? "pointer" : "not-allowed",
            }}
          >
            Submit for review
          </button>
        </div>
      </div>

      <MobileTabBar active="current" />
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
      className="flex md:hidden shrink-0 fixed bottom-0 left-0 right-0 z-50"
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
          className="flex-1 flex items-center justify-center text-[11px] font-semibold"
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
