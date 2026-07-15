"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { triggerAgent, pollIncident, fetchInternalAgentRuns, type InternalAgentRunSummary } from "@/lib/api";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MetricCard } from "@/components/ui/MetricCard";

const POLL_INTERVAL_MS = 2000;

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diffMs / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

interface GapRecommendation {
  gap_description: string;
  suggested_agent_name: string;
  confidence: number;
  estimated_build_effort: string;
}

interface GapScanResult {
  days_back: number;
  runs_analyzed: number;
  corrections_analyzed: number;
  chat_queries_analyzed: number;
  recommendations: GapRecommendation[];
}

interface QualityIssue {
  file: string;
  line: number;
  issue_type: string;
  description: string;
  severity: string;
}

interface QualitySweepResult {
  files_reviewed: number;
  blocking_count: number;
  non_blocking_count: number;
  issues: QualityIssue[];
}

type CheckState = "idle" | "running" | "error";

function shortFile(path: string): string {
  const marker = "kdavis-agentic-platform/";
  const idx = path.indexOf(marker);
  return idx >= 0 ? path.slice(idx + marker.length) : path;
}

/** Fires an internal agent, polls to completion, and renders the real
 * result inline — distinct from FireButton, which only shows a checkmark.
 * Kelvin asked for this panel to show what a check actually found, not
 * just that it finished. */
function HealthCheckTrigger<TResult>({
  agentId,
  label,
  payload,
  renderResult,
  onComplete,
}: {
  agentId: string;
  label: string;
  payload: Record<string, unknown>;
  renderResult: (result: TResult) => React.ReactNode;
  onComplete?: () => void;
}) {
  const [state, setState] = useState<CheckState>("idle");
  const [result, setResult] = useState<TResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const supabase = createClient();

  async function run() {
    if (state === "running") return;
    setState("running");
    setResult(null);
    setErrorMsg(null);

    try {
      const { data: { session } } = await supabase.auth.getSession();
      const authToken = session?.access_token;
      if (!authToken) {
        setState("error");
        setErrorMsg("Not signed in");
        return;
      }

      const trigger = await triggerAgent(agentId, payload, authToken);
      const runId = trigger.runId;

      const poll = async (): Promise<void> => {
        const outcome = await pollIncident(agentId, runId, authToken);
        if (outcome.status === "executed") {
          setResult(outcome.result as TResult);
          setState("idle");
          onComplete?.();
        } else if (outcome.status === "failed" || outcome.status === "budget_exceeded") {
          setState("error");
          setErrorMsg(outcome.error ?? "Check failed");
        } else {
          setTimeout(poll, POLL_INTERVAL_MS);
        }
      };
      setTimeout(poll, POLL_INTERVAL_MS);
    } catch (err) {
      setState("error");
      setErrorMsg(err instanceof Error ? err.message : "Trigger failed");
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        onClick={run}
        disabled={state === "running"}
        className="self-start px-3.5 py-2 rounded-[6px] text-[11px] font-mono font-semibold inline-flex items-center gap-1.5 transition-colors"
        style={
          state === "running"
            ? { border: "1px solid #e8963f", color: "#e8963f", backgroundColor: "transparent", cursor: "default" }
            : { border: "1px solid #5eead4", color: "#5eead4", backgroundColor: "#5eead41a" }
        }
      >
        {state === "running" && (
          <span
            className="inline-block w-2.5 h-2.5 rounded-full animate-spin shrink-0"
            style={{ border: "2px solid #e8963f55", borderTopColor: "#e8963f" }}
          />
        )}
        {state === "running" ? "Running…" : label}
      </button>
      {state === "error" && errorMsg && (
        <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>
          ✕ {errorMsg}
        </p>
      )}
      {result && renderResult(result)}
    </div>
  );
}

function GapScanResultView({ result }: { result: GapScanResult }) {
  return (
    <div
      className="rounded-[10px] p-3.5"
      style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
    >
      <p className="text-[11px] font-mono mb-2.5" style={{ color: "#5b6673" }}>
        {result.runs_analyzed} run{result.runs_analyzed === 1 ? "" : "s"}, {result.corrections_analyzed} correction
        {result.corrections_analyzed === 1 ? "" : "s"}, {result.chat_queries_analyzed} chat quer
        {result.chat_queries_analyzed === 1 ? "y" : "ies"} analyzed ({result.days_back}d window)
      </p>
      {result.recommendations.length === 0 ? (
        <p className="text-[12px]" style={{ color: "#6fce8f" }}>No gaps found.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {result.recommendations.map((rec, i) => (
            <div key={i} className="flex items-start gap-2.5" style={{ borderTop: i > 0 ? "1px solid #1c222b" : "none", paddingTop: i > 0 ? "8px" : "0" }}>
              <span
                className="text-[10px] font-mono font-semibold shrink-0 mt-0.5"
                style={{ color: "#e8963f" }}
              >
                {Math.round(rec.confidence * 100)}%
              </span>
              <div className="min-w-0">
                <p className="text-[12px] font-semibold" style={{ color: "#eef2f5" }}>{rec.gap_description}</p>
                <p className="text-[10.5px] font-mono" style={{ color: "#5b6673" }}>
                  suggested: {rec.suggested_agent_name} · {rec.estimated_build_effort}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function QualitySweepResultView({ result }: { result: QualitySweepResult }) {
  const topBlocking = result.issues.filter((i) => i.severity === "blocking").slice(0, 8);
  return (
    <div
      className="rounded-[10px] p-3.5"
      style={{ backgroundColor: "#10151b", border: "1px solid #1c222b" }}
    >
      <div className="flex items-center gap-4 mb-2.5">
        <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          {result.files_reviewed} files reviewed
        </span>
        <span className="text-[11px] font-mono" style={{ color: result.blocking_count > 0 ? "#e05d5d" : "#6fce8f" }}>
          {result.blocking_count} blocking
        </span>
        <span className="text-[11px] font-mono" style={{ color: "#e8963f" }}>
          {result.non_blocking_count} non-blocking
        </span>
      </div>
      {topBlocking.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {topBlocking.map((issue, i) => (
            <p key={i} className="text-[11px] font-mono truncate-text" style={{ color: "#9aa2ab" }}>
              <span style={{ color: "#e05d5d" }}>{shortFile(issue.file)}:{issue.line}</span> — {issue.description}
            </p>
          ))}
          {result.blocking_count > topBlocking.length && (
            <p className="text-[10.5px] font-mono" style={{ color: "#5b6673" }}>
              +{result.blocking_count - topBlocking.length} more (full report in the JSON download)
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function SystemHealthPanel() {
  const [runs, setRuns] = useState<InternalAgentRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  async function loadRuns() {
    const { data: { session } } = await supabase.auth.getSession();
    const authToken = session?.access_token;
    if (!authToken) {
      setLoading(false);
      return;
    }
    try {
      const recent = await fetchInternalAgentRuns(authToken, 15);
      setRuns(recent);
    } catch {
      // Real data or nothing — never show stale/fake rows on a fetch error.
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const errorCount = runs.filter((r) => r.status === "failed").length;
  const executedCount = runs.filter((r) => r.status === "executed").length;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        <MetricCard label="Recent Runs" value={String(runs.length)} accent="#5eead4" />
        <MetricCard label="Succeeded" value={String(executedCount)} accent="#6fce8f" />
        <MetricCard
          label="Failed"
          value={String(errorCount)}
          accent={errorCount > 0 ? "#e05d5d" : "#5eead4"}
        />
      </div>

      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
        <HealthCheckTrigger<GapScanResult>
          agentId="gap_detector_agent"
          label="Run Gap Scan Now"
          payload={{ days_back: 30 }}
          renderResult={(result) => <GapScanResultView result={result} />}
          onComplete={loadRuns}
        />
        <HealthCheckTrigger<QualitySweepResult>
          agentId="code_quality_agent"
          label="Run Code Quality Sweep Now"
          payload={{ full_sweep: true }}
          renderResult={(result) => <QualitySweepResultView result={result} />}
          onComplete={loadRuns}
        />
      </div>

      <div>
        <p className="text-[11px] font-mono uppercase tracking-wider mb-2.5" style={{ color: "#5b6673" }}>
          Recent Internal-Agent Runs
        </p>
        {loading ? (
          <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading…</p>
        ) : runs.length === 0 ? (
          <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
            No internal-agent runs yet — fire one of the checks above, or a fire button elsewhere in the dashboard.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["Agent", "Status", "Requested By", "When", "Error"].map((h) => (
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
                {runs.map((run) => (
                  <tr key={run.run_id}>
                    <td className="font-semibold" style={{ color: "#eef2f5", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                      {run.agent_id}
                    </td>
                    <td style={{ padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="font-mono" style={{ color: "#5b6673", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                      {run.requested_by_email ?? "—"}
                    </td>
                    <td className="font-mono" style={{ color: "#5b6673", padding: "9px 16px 9px 0", borderTop: "1px solid #1c222b" }}>
                      {formatRelative(run.created_at)}
                    </td>
                    <td className="font-mono truncate-text" style={{ color: "#e05d5d", padding: "9px 0", borderTop: "1px solid #1c222b", maxWidth: "240px" }}>
                      {run.error ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
