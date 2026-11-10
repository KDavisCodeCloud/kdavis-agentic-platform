import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { OutreachSection } from "@/components/ui/OutreachSection";

// Partners tab (Kelvin, 2026-11-09: "partners need their own tab"). Referral
// partners -- AI agencies, fractional CISOs, compliance and audit firms, VC
// platform teams -- used to share the Marketing page's Outreach card. They
// are a different relationship with a different rhythm (manual LinkedIn, a
// daily block of notes), so they get a page of their own. Same lanes and
// approval rules as Outreach: OutreachSection in "partners" mode.
export default function PartnersPage() {
  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Partners" />
      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <SectionCard
          title="Referral partners"
          status="live"
          statusNote="firms that send you clients · partnership notes pasted by hand on LinkedIn · nothing sends without approval"
        >
          <OutreachSection mode="partners" />
        </SectionCard>
      </div>
    </div>
  );
}
