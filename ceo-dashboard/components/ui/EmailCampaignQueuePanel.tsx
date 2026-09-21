"use client";

import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "./StatusBadge";
import {
  fetchTemplates, fetchTemplateDetail, updateTemplate, approveTemplate, retireTemplate,
} from "@/lib/email-campaigns-api";
import type { EmailCampaignTemplate, EmailCampaignTemplateDetail, EmailFeedSource } from "@/lib/types";

const FEEDS: { source: EmailFeedSource; label: string; pendingStatus: string }[] = [
  { source: "cloud-decoded", label: "Cloud Decoded", pendingStatus: "pending_approval" },
  { source: "mse", label: "MSE", pendingStatus: "pending_hitl" },
];

type EditState = { subject: string; preheader: string; body_html: string; body_text: string; cta_url: string };

export function EmailCampaignQueuePanel() {
  const [templates, setTemplates] = useState<EmailCampaignTemplate[]>([]);
  const [feedErrors, setFeedErrors] = useState<Record<EmailFeedSource, string | null>>({ "cloud-decoded": null, mse: null });
  const [loading, setLoading] = useState(true);
  const [showAllStatuses, setShowAllStatuses] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<"all" | EmailFeedSource>("all");
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<EmailCampaignTemplateDetail | null>(null);
  const [edit, setEdit] = useState<EditState | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const results = await Promise.all(
      FEEDS.map(async (feed) => {
        try {
          const rows = await fetchTemplates(feed.source, showAllStatuses ? undefined : feed.pendingStatus);
          return { source: feed.source, rows, error: null as string | null };
        } catch (err) {
          return { source: feed.source, rows: [] as EmailCampaignTemplate[], error: err instanceof Error ? err.message : "Failed to load" };
        }
      })
    );
    setTemplates(results.flatMap((r) => r.rows));
    setFeedErrors({
      "cloud-decoded": results.find((r) => r.source === "cloud-decoded")?.error ?? null,
      mse: results.find((r) => r.source === "mse")?.error ?? null,
    });
    setLoading(false);
  }, [showAllStatuses]);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleExpand(t: EmailCampaignTemplate) {
    const key = `${t.source}:${t.templateKey}`;
    if (expandedKey === key) {
      setExpandedKey(null);
      setDetail(null);
      setEdit(null);
      return;
    }
    setExpandedKey(key);
    setDetail(null);
    setEdit(null);
    try {
      const d = await fetchTemplateDetail(t.source, t.templateKey);
      setDetail(d);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to load template detail");
    }
  }

  async function handleApprove(t: EmailCampaignTemplate) {
    setBusyKey(t.templateKey);
    setActionError(null);
    try {
      await approveTemplate(t.source, t.templateKey);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Approve failed");
    } finally {
      setBusyKey(null);
    }
  }

  async function handleRetire(t: EmailCampaignTemplate) {
    if (!confirm(`Retire ${t.templateKey}? This cannot be undone from this panel.`)) return;
    setBusyKey(t.templateKey);
    setActionError(null);
    try {
      await retireTemplate(t.source, t.templateKey);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Retire failed");
    } finally {
      setBusyKey(null);
    }
  }

  async function handleSaveEdit(t: EmailCampaignTemplate) {
    if (!edit) return;
    setBusyKey(t.templateKey);
    setActionError(null);
    try {
      await updateTemplate(t.templateKey, edit);
      setExpandedKey(null);
      setEdit(null);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusyKey(null);
    }
  }

  async function handleApproveAllVisible() {
    const visible = templates.filter((t) => sourceFilter === "all" || t.source === sourceFilter);
    const approvable = visible.filter((t) => t.status === "pending_approval" || t.status === "pending_hitl" || t.status === "loaded_unactivated");
    if (approvable.length === 0) return;
    if (!confirm(`Approve all ${approvable.length} visible pending template(s)?`)) return;
    setActionError(null);
    for (const t of approvable) {
      setBusyKey(t.templateKey);
      try {
        await approveTemplate(t.source, t.templateKey);
      } catch (err) {
        setActionError(`Stopped at ${t.templateKey}: ${err instanceof Error ? err.message : "approve failed"}`);
        setBusyKey(null);
        await load();
        return;
      }
    }
    setBusyKey(null);
    await load();
  }

  const visible = templates
    .filter((t) => sourceFilter === "all" || t.source === sourceFilter)
    .sort((a, b) => a.sequenceKey.localeCompare(b.sequenceKey) || (a.stepNumber ?? 0) - (b.stepNumber ?? 0));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as "all" | EmailFeedSource)}
          className="font-mono px-2 py-1 rounded-[6px]"
          style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", minHeight: 32, fontSize: 11 }}
        >
          <option value="all">All products</option>
          <option value="cloud-decoded">Cloud Decoded</option>
          <option value="mse">MSE</option>
        </select>

        <label className="flex items-center gap-1.5 text-[11px] font-mono" style={{ color: "#8b96a3" }}>
          <input type="checkbox" checked={showAllStatuses} onChange={(e) => setShowAllStatuses(e.target.checked)} />
          Show all statuses (not just pending)
        </label>

        <button
          onClick={handleApproveAllVisible}
          disabled={busyKey !== null}
          className="ml-auto px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold"
          style={{ border: "1px solid #5eead4", color: busyKey ? "#5b6673" : "#5eead4", backgroundColor: "#5eead41a" }}
        >
          Approve all visible
        </button>
      </div>

      {(feedErrors["cloud-decoded"] || feedErrors.mse) && (
        <div className="mb-3 space-y-1">
          {feedErrors["cloud-decoded"] && (
            <p className="text-[11px] font-mono px-2 py-1.5 rounded-[6px]" style={{ backgroundColor: "#e05d5d1a", color: "#e05d5d" }}>
              Cloud Decoded feed: {feedErrors["cloud-decoded"]}
            </p>
          )}
          {feedErrors.mse && (
            <p className="text-[11px] font-mono px-2 py-1.5 rounded-[6px]" style={{ backgroundColor: "#e05d5d1a", color: "#e05d5d" }}>
              MSE feed: {feedErrors.mse}
            </p>
          )}
        </div>
      )}

      {actionError && (
        <p className="text-[11px] font-mono mb-3" style={{ color: "#e05d5d" }}>{actionError}</p>
      )}

      {loading ? (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading…</p>
      ) : visible.length === 0 ? (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          Nothing here — {showAllStatuses ? "no templates match this filter." : "no templates pending approval."}
        </p>
      ) : (
        <div className="space-y-1.5">
          {visible.map((t) => {
            const key = `${t.source}:${t.templateKey}`;
            const isExpanded = expandedKey === key;
            const canEdit = t.source === "cloud-decoded";
            const canApprove = t.status === "pending_approval" || t.status === "pending_hitl" || t.status === "loaded_unactivated";
            return (
              <div key={key} style={{ border: "1px solid #1c222b", borderRadius: 8 }}>
                <div
                  onClick={() => toggleExpand(t)}
                  className="flex items-center gap-2 flex-wrap cursor-pointer px-3 py-2"
                  style={{ minWidth: 0 }}
                >
                  <span
                    className="text-[9.5px] font-mono font-semibold px-1.5 py-0.5 rounded shrink-0"
                    style={{ backgroundColor: t.source === "cloud-decoded" ? "#5eead41a" : "#5b8def22", color: t.source === "cloud-decoded" ? "#5eead4" : "#7ea6f5" }}
                  >
                    {t.source === "cloud-decoded" ? "CD" : "MSE"}
                  </span>
                  <span className="text-[11px] font-mono truncate" style={{ color: "#8b96a3", maxWidth: 160 }}>
                    {t.sequenceKey}{t.stepNumber !== null ? ` · step ${t.stepNumber}` : ""}
                  </span>
                  <span className="text-[12px] truncate flex-1" style={{ color: "#eef2f5", minWidth: 0 }}>
                    {t.subject ?? "(no subject)"}
                  </span>
                  {!t.productResolved && (
                    <span className="text-[9.5px] font-mono px-1.5 py-0.5 rounded" style={{ backgroundColor: "#e05d5d22", color: "#e05d5d" }}>
                      UNRESOLVED PRODUCT
                    </span>
                  )}
                  <StatusBadge status={t.status} />
                  <span className="text-[10px] font-mono shrink-0" style={{ color: "#5b6673" }}>{t.productLabel}</span>
                </div>

                {isExpanded && (
                  <div className="px-3 pb-3 pt-1" style={{ borderTop: "1px solid #1c222b" }} onClick={(e) => e.stopPropagation()}>
                    {!detail ? (
                      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading detail…</p>
                    ) : canEdit ? (
                      <EditForm
                        detail={detail}
                        edit={edit ?? { subject: detail.subject ?? "", preheader: detail.preheader ?? "", body_html: detail.bodyHtml ?? "", body_text: detail.bodyText ?? "", cta_url: detail.ctaUrl ?? "" }}
                        onChange={setEdit}
                      />
                    ) : (
                      <div className="space-y-1">
                        <p className="text-[11px] font-mono" style={{ color: "#8b96a3" }}>Preheader: {detail.preheader ?? "—"}</p>
                        <p className="text-[11px] font-mono" style={{ color: "#8b96a3" }}>Origin: {detail.origin}</p>
                        <p className="text-[11px] font-mono whitespace-pre-wrap" style={{ color: "#aab4bd" }}>
                          {detail.bodyText ?? "(no plain-text body on this feed's contract)"}
                        </p>
                      </div>
                    )}

                    <div className="flex items-center gap-2 mt-3">
                      {canApprove && (
                        <button
                          onClick={() => handleApprove(t)}
                          disabled={busyKey === t.templateKey}
                          className="px-3 py-1 rounded-[6px] text-[11px] font-mono font-semibold"
                          style={{ border: "1px solid #6fce8f", color: "#6fce8f", backgroundColor: "#6fce8f1a" }}
                        >
                          Approve
                        </button>
                      )}
                      {canEdit && detail && (
                        <button
                          onClick={() => handleSaveEdit(t)}
                          disabled={busyKey === t.templateKey || !edit}
                          className="px-3 py-1 rounded-[6px] text-[11px] font-mono font-semibold"
                          style={{ border: "1px solid #7ea6f5", color: "#7ea6f5", backgroundColor: "#5b8def22" }}
                        >
                          Save (resets to pending)
                        </button>
                      )}
                      <button
                        onClick={() => handleRetire(t)}
                        disabled={busyKey === t.templateKey}
                        className="px-3 py-1 rounded-[6px] text-[11px] font-mono font-semibold"
                        style={{ border: "1px solid #9aa2ab", color: "#9aa2ab", backgroundColor: "transparent" }}
                      >
                        Retire
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EditForm({ edit, onChange }: { detail: EmailCampaignTemplateDetail; edit: EditState; onChange: (e: EditState) => void }) {
  const fieldStyle = { backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", fontSize: 11, width: "100%" } as const;
  return (
    <div className="space-y-2">
      <input value={edit.subject} onChange={(e) => onChange({ ...edit, subject: e.target.value })} placeholder="Subject" className="font-mono px-2 py-1 rounded-[6px]" style={fieldStyle} />
      <input value={edit.preheader} onChange={(e) => onChange({ ...edit, preheader: e.target.value })} placeholder="Preheader" className="font-mono px-2 py-1 rounded-[6px]" style={fieldStyle} />
      <input value={edit.cta_url} onChange={(e) => onChange({ ...edit, cta_url: e.target.value })} placeholder="CTA URL" className="font-mono px-2 py-1 rounded-[6px]" style={fieldStyle} />
      <textarea value={edit.body_text} onChange={(e) => onChange({ ...edit, body_text: e.target.value })} placeholder="Plain-text body" rows={6} className="font-mono px-2 py-1.5 rounded-[6px]" style={fieldStyle} />
      <textarea value={edit.body_html} onChange={(e) => onChange({ ...edit, body_html: e.target.value })} placeholder="HTML body" rows={6} className="font-mono px-2 py-1.5 rounded-[6px]" style={fieldStyle} />
    </div>
  );
}
