import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { EmailCampaignQueuePanel } from "@/components/ui/EmailCampaignQueuePanel";
import { EmailCampaignSequencesPanel } from "@/components/ui/EmailCampaignSequencesPanel";
import { EmailCampaignMseStatusPanel } from "@/components/ui/EmailCampaignMseStatusPanel";
import { EmailCampaignMetricsPanel } from "@/components/ui/EmailCampaignMetricsPanel";

// Unified HITL queue over two real, live backends (2026-09-21):
//   - Cloud Decoded's own email lifecycle engine (this repo's root,
//     docs/internal/email-approval-api.md) -- full per-step template
//     schema, sequence activation, click/send metrics.
//   - MSE's campaign engine (kdavis-microsaas-engine, a separate repo,
//     its own docs/internal/email-approval-api.md) -- wraps the real
//     mse_email_sequences table as it actually exists, not the parallel
//     schema the original build plan assumed. No send/click tracking
//     exists there yet -- see EmailCampaignMetricsPanel's "not tracked
//     yet" rendering and EmailCampaignMseStatusPanel's positioning-gate
//     status table.
// Both feeds are admin-only: neither backend has a "hitl" role yet, and
// this app's own Role type doesn't either -- see lib/email-campaigns/route-helpers.ts.
export default function EmailCampaignsPage() {
  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Email Campaigns" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          <SectionCard
            title="Approval Queue"
            status="live"
            statusNote="Cloud Decoded cd_email_templates (live) + MSE mse_email_sequences (live, wrapped) — admin-only, no hitl role on either backend yet"
          >
            <EmailCampaignQueuePanel />
          </SectionCard>

          <SectionCard
            title="Cloud Decoded Sequences"
            status="partial"
            statusNote="Activate/deactivate is real — no endpoint reports current active state, see panel note"
          >
            <EmailCampaignSequencesPanel />
          </SectionCard>

          <SectionCard
            title="MSE Campaign Status"
            status="partial"
            statusNote="Real positioning-gate state per product — Generate Campaign not wired, see panel note"
          >
            <EmailCampaignMseStatusPanel />
          </SectionCard>

          <SectionCard
            title="Metrics"
            status="partial"
            statusNote="Cloud Decoded sends/clicks/revenue are real — MSE has no tracking tables yet, renders 'not tracked yet'"
          >
            <EmailCampaignMetricsPanel />
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
