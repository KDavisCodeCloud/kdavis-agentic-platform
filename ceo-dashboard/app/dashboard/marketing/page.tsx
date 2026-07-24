import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { AgentRosterCard } from "@/components/ui/AgentRosterCard";
import { LinkedInBatchReview } from "@/components/ui/LinkedInBatchReview";

const PIPELINE_STAGES = [
  { stage: "Cold",      count: 0, mrr_potential: "$0" },
  { stage: "Contacted", count: 0, mrr_potential: "$0" },
  { stage: "Demo",      count: 0, mrr_potential: "$0" },
  { stage: "Trial",     count: 0, mrr_potential: "$0" },
  { stage: "Paying",    count: 0, mrr_potential: "$0" },
];

const MARKETING_AGENTS = [
  { name: "LinkedIn Content",   status: "active",   lastRun: null, output: "MKT-LI1 — monthly batch, ~12 posts" },
  { name: "Cold Email",         status: "pending",  lastRun: null, output: "Not yet built" },
  { name: "Conversion Tracker", status: "pending",  lastRun: null, output: "Not yet built" },
];

const OUTREACH = [
  { sequence: "MSE Intro Sequence", product: "MSE", sent: 0, opens: "—", meetings: 0 },
];

export default function MarketingPage() {
  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Marketing & Sales" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Pipeline Stages */}
          <SectionCard title="Sales Pipeline">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
              {PIPELINE_STAGES.map((stage) => (
                <div
                  key={stage.stage}
                  className="rounded-[10px] p-3.5 text-center"
                  style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
                >
                  <p className="text-[11px] font-mono uppercase mb-2" style={{ color: "#5b6673" }}>
                    {stage.stage}
                  </p>
                  <p className="text-[22px] font-extrabold mb-1" style={{ color: "#eef2f5" }}>
                    {stage.count}
                  </p>
                  <p className="text-[11px] font-mono" style={{ color: "#5eead4" }}>
                    {stage.mrr_potential}
                  </p>
                </div>
              ))}
            </div>
          </SectionCard>

          {/* LinkedIn Monthly Batch — MKT-LI1's ~12 posts, review/approve/schedule */}
          <SectionCard title="LinkedIn Monthly Batch">
            <LinkedInBatchReview />
          </SectionCard>

          {/* Marketing Agents */}
          <SectionCard title="Marketing Agents">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              {MARKETING_AGENTS.map((a) => (
                <AgentRosterCard key={a.name} {...a} />
              ))}
            </div>
          </SectionCard>

          {/* Cold Outreach Tracker */}
          <SectionCard title="Cold Outreach Tracker">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Sequence", "Product", "Sent", "Open Rate", "Meetings"].map((h) => (
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
                  {OUTREACH.map((row) => (
                    <tr key={row.sequence}>
                      <td className="font-semibold" style={{ color: "#eef2f5", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.sequence}
                      </td>
                      <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.product}
                      </td>
                      <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.sent}
                      </td>
                      <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.opens}
                      </td>
                      <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 0", borderTop: "1px solid #1c222b" }}>
                        {row.meetings}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
