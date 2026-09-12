import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { WorkspaceAdminPanel } from "@/components/ui/WorkspaceAdminPanel";

export default function CustomersPage() {
  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Customers" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="space-y-5">
          <SectionCard
            title="Cloud Decoded Workspaces"
            status="live"
            statusNote="api/routes/internal_workspaces.py -- suspend/reactivate/rotate-token are real, not mocked"
          >
            <WorkspaceAdminPanel />
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
