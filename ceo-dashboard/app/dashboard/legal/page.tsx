import { createClient } from "@/lib/supabase/server";
import { TopBar } from "@/components/shell/TopBar";
import { SectionCard } from "@/components/ui/SectionCard";
import { AgentRosterCard } from "@/components/ui/AgentRosterCard";
import type { LegalDocument } from "@/lib/types";

const LEGAL_AGENTS = [
  { name: "Contract Review", status: "pending", lastRun: null, output: "Not yet built" },
  { name: "Entity Advisor",  status: "pending", lastRun: null, output: "Not yet built" },
  { name: "IP Flagging",     status: "pending", lastRun: null, output: "Not yet built" },
];

export default async function LegalPage() {
  const supabase = await createClient();
  const { data: docs } = await supabase
    .from("legal_documents")
    .select("*")
    .order("last_updated_at", { ascending: false });

  const documents = (docs ?? []) as LegalDocument[];

  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Legal" />

      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        {/* Persistent legal disclaimer — always first */}
        <div
          className="rounded-[10px] p-4 mb-5"
          style={{ backgroundColor: "#241a10", border: "1px solid #3d2e1f" }}
        >
          <p className="text-[12px] font-semibold" style={{ color: "#e8963f" }}>
            ⚠ AI-Assisted Information Only
          </p>
          <p className="text-[11.5px] mt-1" style={{ color: "#aab4bd" }}>
            This department shows AI-assisted legal information, not legal advice. Consult a licensed attorney before acting on anything shown here. All AI responses are logged for review.
          </p>
        </div>

        <div className="space-y-5">
          {/* Document Vault */}
          <SectionCard title="Document Vault">
            {documents.length === 0 ? (
              <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
                No documents yet. Add legal documents to the legal_documents table.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["Document", "Product", "Version", "Last Updated"].map((h) => (
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
                    {documents.map((doc) => (
                      <tr key={doc.id}>
                        <td className="font-semibold" style={{ color: "#eef2f5", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                          {doc.doc_name}
                          {/* TODO: add real download link when storage_path is populated */}
                        </td>
                        <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                          {doc.product ?? "—"}
                        </td>
                        <td className="font-mono" style={{ color: "#aab4bd", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                          v{doc.version}
                        </td>
                        <td className="font-mono" style={{ color: "#5b6673", padding: "9px 0", borderTop: "1px solid #1c222b" }}>
                          {new Date(doc.last_updated_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {/* Legal Agent Roster */}
          <SectionCard title="Legal Agents">
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              {LEGAL_AGENTS.map((a) => (
                <AgentRosterCard key={a.name} {...a} />
              ))}
            </div>
          </SectionCard>

          {/* Legal Q&A */}
          <SectionCard title="Legal Q&A (AI-Assisted)">
            <div
              className="rounded-[8px] p-3.5 mb-3"
              style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
            >
              <p className="text-[11px] font-mono mb-1" style={{ color: "#5b6673" }}>
                Example logged response:
              </p>
              <p className="text-[12px] mb-2" style={{ color: "#eef2f5" }}>
                Q: Does my SaaS Terms of Service need a governing law clause?
              </p>
              <p className="text-[12px]" style={{ color: "#aab4bd" }}>
                A: Yes — a governing law clause specifies which state&apos;s laws apply in disputes. For Arizona-based entities (Maricopa County), Arizona law is typically specified. Source: NOLO Business Law FAQ. <em style={{ color: "#e8963f", fontSize: "11px" }}>Attorney caveat: verify with licensed Arizona counsel before finalizing.</em>
              </p>
            </div>
            {/* TODO: wire to /ceo/legal/query FastAPI route and log all responses */}
            <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
              Live Q&A input coming in production build. All responses will be logged with timestamp.
            </p>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
