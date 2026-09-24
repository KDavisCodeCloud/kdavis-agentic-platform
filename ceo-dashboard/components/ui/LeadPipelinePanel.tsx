"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  listIcpProducts,
  triggerLeadFinder,
  triggerSendSequences,
  fetchPipelineSummary,
  fetchLeadFinderRun,
  fetchLeads,
  type IcpProduct,
  type PipelineSummary,
  type LeadFinderRun,
  type Lead,
} from "@/lib/api";

const POLL_INTERVAL_MS = 4000;

// email_status / status badge colors -- same mapping as every other status
// pill in this dashboard (green=good, blue=pending, amber=caution,
// red=bad, gray=neutral).
const EMAIL_STATUS_COLOR: Record<string, string> = {
  verified: "#6fce8f",
  catch_all: "#e8963f",
  unverified: "#9aa2ab",
  invalid: "#e05d5d",
  bounced: "#e05d5d",
};

const LEAD_STATUS_COLOR: Record<string, string> = {
  pending_dm: "#9aa2ab",
  pending_email: "#7ea6f5",
  contacted: "#7ea6f5",
  converted: "#6fce8f",
  unsubscribed: "#9aa2ab",
  bounced: "#e05d5d",
};

function formatWhenFound(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffMinutes = Math.round(diffMs / 60000);
  if (diffMinutes < 1) return "just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return new Date(iso).toLocaleDateString();
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  return remainderMinutes ? `${hours}h ${remainderMinutes}m` : `${hours}h`;
}

const STAGE_ORDER = ["new", "contacted", "replied", "qualified", "demo", "won", "lost"];

// Manual fallback for the two scheduled n8n crons that actually move leads
// through the pipeline (lead_finder_workflow.json, Sunday 6am MST; and
// outreach-sender-workflow.json, hourly) -- for when n8n itself is down
// and the weekly/hourly run needs to happen anyway. Both buttons proxy to
// the exact same backend endpoints those workflows call.
export function LeadPipelinePanel() {
  const [products, setProducts] = useState<IcpProduct[]>([]);
  const [productId, setProductId] = useState<string>("");
  const [summary, setSummary] = useState<PipelineSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [finding, setFinding] = useState(false);
  const [sending, setSending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<string | null>(null);

  const [run, setRun] = useState<LeadFinderRun | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const pollHandle = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickHandle = useRef<ReturnType<typeof setInterval> | null>(null);

  const [leads, setLeads] = useState<Lead[]>([]);
  const [leadsLoading, setLeadsLoading] = useState(false);
  const [leadsError, setLeadsError] = useState<string | null>(null);

  const loadLeads = useCallback((forProductId: string) => {
    if (!forProductId) return;
    setLeadsLoading(true);
    setLeadsError(null);
    fetchLeads({ productId: forProductId, limit: 50 })
      .then((res) => setLeads(res.leads))
      .catch((err) => setLeadsError(err instanceof Error ? err.message : "Loading leads failed"))
      .finally(() => setLeadsLoading(false));
  }, []);

  function stopPolling() {
    if (pollHandle.current) clearInterval(pollHandle.current);
    if (tickHandle.current) clearInterval(tickHandle.current);
    pollHandle.current = null;
    tickHandle.current = null;
  }

  function startPolling(runId: string) {
    stopPolling();
    setElapsedSeconds(0);

    tickHandle.current = setInterval(() => {
      setElapsedSeconds((s) => s + 1);
    }, 1000);

    const poll = async () => {
      try {
        const latest = await fetchLeadFinderRun(runId);
        setRun(latest);
        if (latest.status === "complete" || latest.status === "failed") {
          stopPolling();
          setActionResult(
            latest.status === "complete"
              ? `Done — ${latest.leads_found} lead(s) found, ${latest.leads_verified} verified.`
              : null
          );
          if (latest.status === "failed") {
            setActionError(latest.error_message ?? "Lead finder run failed");
          } else {
            // The run just wrote new rows to mse_leads -- pull them in so
            // the list below reflects this run's results without a manual
            // reload.
            loadLeads(latest.product_id);
          }
        }
      } catch (err) {
        // A transient poll failure shouldn't kill the whole progress
        // display -- just try again next interval.
        setActionError((prev) => prev ?? (err instanceof Error ? err.message : "Checking run status failed"));
      }
    };

    poll();
    pollHandle.current = setInterval(poll, POLL_INTERVAL_MS);
  }

  useEffect(() => stopPolling, []);

  useEffect(() => {
    listIcpProducts()
      .then((rows) => {
        setProducts(rows);
        if (rows.length) setProductId(rows[0].product_id);
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Loading products failed"));

    fetchPipelineSummary()
      .then(setSummary)
      .catch((err) => setLoadError((prev) => prev ?? (err instanceof Error ? err.message : "Loading pipeline summary failed")));
  }, []);

  useEffect(() => {
    if (productId) loadLeads(productId);
  }, [productId, loadLeads]);

  async function runFinder() {
    if (!productId) return;
    setFinding(true);
    setActionError(null);
    setActionResult(null);
    setRun(null);
    try {
      const { run_id: runId } = await triggerLeadFinder(productId);
      startPolling(runId);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Triggering lead finder failed");
    } finally {
      setFinding(false);
    }
  }

  async function runSendSequences() {
    setSending(true);
    setActionError(null);
    setActionResult(null);
    try {
      await triggerSendSequences();
      setActionResult("Sequence send triggered — touch_1/touch_2 will go out for anything due right now.");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Triggering sequence send failed");
    } finally {
      setSending(false);
    }
  }

  return (
    <div>
      <p className="text-[11px] font-mono mb-3" style={{ color: "#5b6673" }}>
        Manual fallback for the scheduled n8n crons — the weekly lead finder (Sunday 6am MST) and hourly outreach
        sender. Use these if an n8n outage means a run didn&apos;t fire; each hits the exact same backend endpoint
        the cron does.
      </p>

      {loadError && (
        <p className="text-[11px] font-mono mb-2" style={{ color: "#e05d5d" }}>{loadError}</p>
      )}

      {summary && (
        <div className="grid gap-2 mb-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))" }}>
          {STAGE_ORDER.map((stage) => (
            <div
              key={stage}
              className="rounded-[8px] p-2 text-center"
              style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
            >
              <p className="text-[10px] font-mono uppercase" style={{ color: "#5b6673" }}>{stage}</p>
              <p className="text-[16px] font-extrabold" style={{ color: "#eef2f5" }}>
                {summary.stages[stage] ?? 0}
              </p>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
          disabled={!products.length}
          className="font-mono px-2 py-1 rounded-[6px]"
          style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", minHeight: 44, fontSize: 16 }}
        >
          {products.length === 0 && <option value="">No ICP-configured products</option>}
          {products.map((p) => (
            <option key={p.product_id} value={p.product_id}>
              {p.name}
            </option>
          ))}
        </select>

        <button
          onClick={runFinder}
          disabled={finding || !productId}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors shrink-0"
          style={{
            border: "1px solid #f5a623",
            color: "#f5a623",
            backgroundColor: "transparent",
            opacity: finding || !productId ? 0.6 : 1,
            minHeight: 44,
          }}
          title="Runs the weekly lead finder now for the selected product."
        >
          {finding ? "Starting…" : "Run Lead Finder Now"}
        </button>

        <button
          onClick={runSendSequences}
          disabled={sending}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors shrink-0"
          style={{
            border: "1px solid #5a96ff",
            color: "#5a96ff",
            backgroundColor: "transparent",
            opacity: sending ? 0.6 : 1,
            minHeight: 44,
          }}
          title="Sends any touch_1/touch_2 emails that are due right now."
        >
          {sending ? "Sending…" : "Send Due Sequences Now"}
        </button>
      </div>

      {run && (run.status === "pending" || run.status === "running") && (
        <div className="mt-3 p-2 rounded-[8px]" style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}>
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-[11px] font-mono truncate pr-2" style={{ color: "#c7cfd6" }}>
              {run.current_step ?? (run.status === "pending" ? "Queued…" : "Working…")}
            </p>
            <p className="text-[10px] font-mono shrink-0" style={{ color: "#8b96a3" }}>
              {formatDuration(elapsedSeconds)} elapsed
              {run.estimated_seconds_remaining != null && run.estimated_seconds_remaining > 0
                ? ` · ~${formatDuration(run.estimated_seconds_remaining)} left`
                : ""}
            </p>
          </div>
          <div className="w-full rounded-full overflow-hidden" style={{ height: 5, backgroundColor: "#1c222b" }}>
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: run.total_steps
                  ? `${Math.min(100, Math.round((run.completed_steps / run.total_steps) * 100))}%`
                  : "4%",
                backgroundColor: "#f5a623",
              }}
            />
          </div>
        </div>
      )}

      {actionError && (
        <p className="text-[11px] font-mono mt-2" style={{ color: "#e05d5d" }}>{actionError}</p>
      )}
      {actionResult && (
        <p className="text-[11px] font-mono mt-2" style={{ color: "#6fce8f" }}>{actionResult}</p>
      )}

      <div className="mt-4 pt-3" style={{ borderTop: "1px solid #1c222b" }}>
        <div className="flex items-center justify-between mb-2">
          <p className="text-[13px] font-bold" style={{ color: "#c7cfd6" }}>
            Leads{leads.length ? ` (${leads.length})` : ""}
          </p>
          <button
            onClick={() => productId && loadLeads(productId)}
            disabled={leadsLoading || !productId}
            className="text-[10px] font-mono px-2 py-1 rounded-[6px]"
            style={{
              border: "1px solid #1c222b",
              color: "#8b96a3",
              backgroundColor: "transparent",
              opacity: leadsLoading || !productId ? 0.6 : 1,
              minHeight: 32,
            }}
          >
            {leadsLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {leadsError && (
          <p className="text-[11px] font-mono mb-2" style={{ color: "#e05d5d" }}>{leadsError}</p>
        )}

        {!leadsLoading && !leadsError && leads.length === 0 && (
          <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
            No leads yet for this product — run the lead finder above to find some.
          </p>
        )}

        {leads.length > 0 && (
          <div className="overflow-x-auto rounded-[8px]" style={{ border: "1px solid #1c222b" }}>
            <table className="w-full text-[11px] font-mono" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ backgroundColor: "#10151b" }}>
                  {["Name", "Title", "Company", "Email", "Status", "Source", "LinkedIn", "Found"].map((h) => (
                    <th
                      key={h}
                      className="text-left px-2 py-1.5 uppercase"
                      style={{ color: "#5b6673", fontSize: 10, letterSpacing: "0.04em" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {leads.map((lead) => {
                  const name = [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "—";
                  return (
                    <tr key={lead.id} style={{ borderTop: "1px solid #1c222b" }}>
                      <td className="px-2 py-1.5 whitespace-nowrap" style={{ color: "#eef2f5" }}>{name}</td>
                      <td className="px-2 py-1.5" style={{ color: "#aab4bd", minWidth: 0, maxWidth: 160 }}>
                        <span className="block truncate">{lead.title ?? "—"}</span>
                      </td>
                      <td className="px-2 py-1.5" style={{ color: "#aab4bd", minWidth: 0, maxWidth: 140 }}>
                        <span className="block truncate">{lead.company ?? lead.domain ?? "—"}</span>
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        {lead.email ? (
                          <a href={`mailto:${lead.email}`} style={{ color: "#eef2f5" }} className="hover:underline">
                            {lead.email}
                          </a>
                        ) : (
                          <span style={{ color: "#5b6673" }}>—</span>
                        )}
                        <span
                          className="ml-1.5 px-1.5 py-0.5 rounded-full"
                          style={{
                            fontSize: 9,
                            color: EMAIL_STATUS_COLOR[lead.email_status] ?? "#9aa2ab",
                            backgroundColor: `${EMAIL_STATUS_COLOR[lead.email_status] ?? "#9aa2ab"}22`,
                          }}
                        >
                          {lead.email_status}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        <span
                          className="px-1.5 py-0.5 rounded-full"
                          style={{
                            fontSize: 9,
                            color: LEAD_STATUS_COLOR[lead.status] ?? "#9aa2ab",
                            backgroundColor: `${LEAD_STATUS_COLOR[lead.status] ?? "#9aa2ab"}22`,
                          }}
                        >
                          {lead.status.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap" style={{ color: "#8b96a3" }}>{lead.source}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        {lead.linkedin_url ? (
                          <a
                            href={lead.linkedin_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: "#5a96ff" }}
                            className="hover:underline"
                          >
                            Profile
                          </a>
                        ) : (
                          <span style={{ color: "#5b6673" }}>—</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap" style={{ color: "#5b6673" }}>
                        {formatWhenFound(lead.created_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
