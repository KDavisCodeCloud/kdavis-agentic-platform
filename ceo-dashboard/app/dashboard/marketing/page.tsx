import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { AgentRosterCard } from "@/components/ui/AgentRosterCard";
import { LinkedInBatchPanel } from "@/components/ui/LinkedInBatchPanel";
import { MSEContentReview } from "@/components/ui/MSEContentReview";
import { LeadPipelinePanel } from "@/components/ui/LeadPipelinePanel";
import { OutreachTracker } from "@/components/ui/OutreachTracker";

// Cold Outreach (added 2026-09-16): job-posting-signal scraper +
// per-ICP LinkedIn DM sequences (MKT-O1/MKT-O2, kdavis-microsaas-engine)
// -- was "Cold Email"/"Not yet built" until today; it's LinkedIn DMs, not
// email (the ICP config specifies LinkedIn as the channel, not email --
// see mse_icp_configs). Triggered via the Lead Pipeline panel's "Run Lead
// Finder Now" / "Send Due Sequences Now" buttons above, or the weekly/
// hourly n8n crons those buttons manually fall back for.
const MARKETING_AGENTS = [
  { name: "LinkedIn Content",   status: "active",   lastRun: "2026-08-12", output: "MKT-LI1 — normally ~12 posts/mo, 16-post batch this run" },
  { name: "Cold Outreach",      status: "active",   lastRun: null, output: "MKT-O1/O2 — job-posting scraper + LinkedIn DM sequences, per-ICP. Trigger above in Lead Pipeline." },
  { name: "Conversion Tracker", status: "pending",  lastRun: null, output: "Not yet built" },
];

export default function MarketingPage() {
  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Marketing & Sales" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          {/* Lead Pipeline — real mse_leads.stage counts (DIST Phase 8's
              CRM columns, applied to microsaas-prod 2026-09-07) plus the
              manual n8n-outage fallback for the lead finder / sequence
              sender crons. Replaces the old static "not_built" mock. */}
          <SectionCard title="Lead Pipeline" status="live" statusNote="mse_leads.stage + mse_activities, DIST Phase 8">
            <LeadPipelinePanel />
          </SectionCard>

          {/* LinkedIn Monthly Batch — MKT-LI1's ~12 posts, plus on-demand fire, review/approve/schedule */}
          <SectionCard title="LinkedIn Content" status="live" statusNote="linkedin_content_queue, MKT-LI1 + Gemini">
            <LinkedInBatchPanel />
          </SectionCard>

          {/* MSE Community Content — MKT-V1's Reddit/Facebook posts, review/approve/send */}
          <SectionCard
            title="MSE Community Content"
            status="partial"
            statusNote="mse_social_content, MKT-V1 — review/approve is real; 'sent' is a manual confirmation, no Reddit/Facebook posting API is wired yet"
          >
            <MSEContentReview />
          </SectionCard>

          {/* Marketing Agents */}
          <SectionCard title="Marketing Agents" status="partial" statusNote="LinkedIn Content is real (MKT-LI1) — roster itself is a static list, not a live agent registry">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              {MARKETING_AGENTS.map((a) => (
                <AgentRosterCard key={a.name} {...a} />
              ))}
            </div>
          </SectionCard>

          {/* Cold Outreach Tracker — real per-product sent/meetings counts
              (mse_dm_sequences + mse_leads.stage). Open rate has no real
              signal anywhere in this codebase (no email-open tracking) and
              is shown as "not tracked," not a fabricated number. */}
          <SectionCard title="Cold Outreach Tracker" status="partial" statusNote="mse_dm_sequences + mse_leads.stage — sent/meetings are real, open rate isn't tracked">
            <OutreachTracker />
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
