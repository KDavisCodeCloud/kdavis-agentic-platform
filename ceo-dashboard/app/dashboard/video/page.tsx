import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { AgentRosterCard } from "@/components/ui/AgentRosterCard";

const SCRIPT_QUEUE = [
  { title: "MSE Launch Announcement", product: "MSE",           status: "draft" },
  { title: "CEO Decoded Demo Walkthrough", product: "CEO Decoded", status: "draft" },
];

const HEYGEN_RENDERS = [
  // No renders yet — placeholder state
];

const DISTRIBUTION_QUEUE = [
  // Empty until scripts are approved and rendered
];

const CREATIVE_AGENTS = [
  { name: "Script Agent",      status: "pending", lastRun: null, output: "Not yet built" },
  { name: "HeyGen Render",     status: "pending", lastRun: null, output: "Not yet built" },
  { name: "Distribution Agent",status: "pending", lastRun: null, output: "Not yet built" },
];

function StripedThumbnail() {
  return (
    <div
      className="w-20 h-14 rounded-[6px] shrink-0"
      style={{
        background: "repeating-linear-gradient(45deg, #1c222b 0px, #1c222b 4px, #10151b 4px, #10151b 12px)",
      }}
    />
  );
}

export default function VideoPage() {
  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Video / Creative" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Script Queue */}
          <SectionCard title="Script Queue" status="not_built" statusNote="static mock — no script_queue table or agent exists yet">
            {SCRIPT_QUEUE.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>No scripts queued.</p>
            ) : (
              SCRIPT_QUEUE.map((script, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between py-2.5 min-w-0"
                  style={{ borderTop: i > 0 ? "1px solid #1c222b" : "none" }}
                >
                  <div className="min-w-0">
                    <p className="text-[12.5px] font-semibold truncate-text" style={{ color: "#eef2f5" }}>
                      {script.title}
                    </p>
                    <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                      {script.product}
                    </p>
                  </div>
                  <StatusBadge status={script.status} />
                </div>
              ))
            )}
          </SectionCard>

          {/* HeyGen Render Tracker */}
          <SectionCard title="HeyGen Render Tracker" status="not_built" statusNote="no HeyGen integration exists yet">
            {HEYGEN_RENDERS.length === 0 ? (
              <div className="flex items-center gap-3">
                <StripedThumbnail />
                <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                  No renders yet. Approve scripts to queue HeyGen jobs.
                </p>
              </div>
            ) : null}
          </SectionCard>

          {/* Distribution Queue */}
          <SectionCard title="Distribution Queue" status="not_built" statusNote="no distribution pipeline exists yet">
            {DISTRIBUTION_QUEUE.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No videos queued for distribution. Wife approves before publish.
              </p>
            ) : null}
          </SectionCard>

          {/* Creative Agents */}
          <SectionCard title="Creative Agents" status="not_built" statusNote="no creative/script/render agents exist yet">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              {CREATIVE_AGENTS.map((a) => (
                <AgentRosterCard key={a.name} {...a} />
              ))}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
