import Link from "next/link";
import { TeamShell } from "@/components/shell/TeamShell";
import { TopBar } from "@/components/shell/TopBar";

const RESOURCES = [
  {
    label: "Role Guide",
    description: "Your role definition, responsibilities, and expectations",
    href: "#",
    linkText: "ROLE.md",
  },
  {
    label: "Claude Code How-To",
    description: "Plain-English guide to using Claude Code for builds",
    href: "#",
    linkText: "HOW_TO_USE_CLAUDE_CODE.md",
  },
  {
    label: "Slack",
    description: "Join #code-team and #general for team communication",
    href: "https://slack.com",
    linkText: "Open Slack",
    external: true,
  },
];

export default function ResourcesPage() {
  return (
    <TeamShell>
      <TopBar taskName="Resources" />
      <div className="flex-1 overflow-y-auto p-6 pb-20 md:pb-6 min-w-0">
        <div
          className="rounded-[14px]"
          style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}
        >
          <div className="px-5 pt-5 pb-3">
            <p className="text-[13px] font-bold" style={{ color: "#c7cfd6" }}>
              RESOURCES
            </p>
          </div>

          {RESOURCES.map((res, i) => (
            <div
              key={res.label}
              className="flex items-center justify-between px-5 py-3.5 min-w-0"
              style={{ borderTop: "1px solid #1c2535" }}
            >
              <div className="min-w-0 flex-1 mr-4">
                <p className="text-[13px] font-semibold" style={{ color: "#eef2f5" }}>
                  {res.label}
                </p>
                <p className="text-[11px] font-mono mt-0.5" style={{ color: "#5b6673" }}>
                  {res.description}
                </p>
              </div>
              <a
                href={res.href}
                target={res.external ? "_blank" : undefined}
                rel={res.external ? "noopener noreferrer" : undefined}
                className="shrink-0 flex items-center gap-1.5 text-[11px] font-mono transition-opacity hover:opacity-70"
                style={{ color: "#5eead4" }}
              >
                {res.linkText}
                <span style={{ fontSize: "10px" }}>→</span>
              </a>
            </div>
          ))}
        </div>

        {/* Practice task note */}
        <div
          className="mt-4 rounded-[14px] px-5 py-4"
          style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}
        >
          <p className="text-[13px] font-bold mb-3" style={{ color: "#c7cfd6" }}>
            GETTING STARTED
          </p>
          <div className="space-y-2">
            {[
              "Read your ROLE.md — everything you need to know about your position",
              "Complete the practice task on PRACTICE_TASK.md before real assignments",
              "Ask questions in #code-team on Slack — not via email",
              "Submit work via the Current Task view — not directly in Slack",
            ].map((tip, i) => (
              <div key={i} className="flex gap-2.5 min-w-0">
                <span
                  className="shrink-0 w-4 h-4 rounded flex items-center justify-center text-[9px] font-mono mt-0.5"
                  style={{ backgroundColor: "#5eead422", color: "#5eead4" }}
                >
                  {i + 1}
                </span>
                <p className="text-[12px]" style={{ color: "#aab4bd" }}>{tip}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Mobile bottom tab bar */}
      <nav
        className="flex md:hidden shrink-0 fixed bottom-0 left-0 right-0 z-50"
        style={{
          height: "48px",
          backgroundColor: "#0f1520",
          borderTop: "1px solid #1c2535",
        }}
      >
        {[
          { label: "My Tasks",     href: "/tasks" },
          { label: "Current Task", href: "/current-task" },
          { label: "Resources",    href: "/resources" },
        ].map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className="flex-1 flex items-center justify-center text-[11px] font-semibold"
            style={{
              color: tab.href === "/resources" ? "#5eead4" : "#5b6673",
              borderTop: tab.href === "/resources" ? "2px solid #5eead4" : "2px solid transparent",
            }}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </TeamShell>
  );
}
