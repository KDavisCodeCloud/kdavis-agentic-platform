"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchTemplates, activateSequence, deactivateSequence } from "@/lib/email-campaigns-api";
import type { EmailCampaignTemplate } from "@/lib/types";

interface SequenceRow {
  key: string;
  totalSteps: number;
  approvedSteps: number;
}

// Cloud Decoded-only: MSE's mse_email_sequences rows ARE the whole
// sequence (see EmailCampaignQueuePanel's comment) -- there's nothing to
// "activate" separately there, approving the row is terminal.
//
// Note: the Cloud Decoded contract has activate/deactivate actions but no
// GET endpoint that reports a sequence's current active/inactive state --
// this panel can only show approval progress and let you fire the action,
// not reflect whether a sequence is currently active. Flagged as a gap.
export function EmailCampaignSequencesPanel() {
  const [rows, setRows] = useState<SequenceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const templates = await fetchTemplates("cloud-decoded");
      const bySequence = new Map<string, EmailCampaignTemplate[]>();
      for (const t of templates) {
        bySequence.set(t.sequenceKey, [...(bySequence.get(t.sequenceKey) ?? []), t]);
      }
      const computed: SequenceRow[] = Array.from(bySequence.entries()).map(([key, ts]) => ({
        key,
        totalSteps: ts.length,
        approvedSteps: ts.filter((t) => t.status === "approved").length,
      }));
      setRows(computed.sort((a, b) => a.key.localeCompare(b.key)));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load sequences");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleActivate(row: SequenceRow) {
    if (row.approvedSteps < row.totalSteps) {
      if (!confirm(`${row.key}: only ${row.approvedSteps}/${row.totalSteps} steps are approved. The backend will refuse this — try anyway?`)) return;
    } else if (!confirm(`Activate "${row.key}"? Enrollments already queued for this sequence will begin sending on the next scheduler pass.`)) {
      return;
    }
    setBusyKey(row.key);
    setActionError(null);
    setLastAction(null);
    try {
      await activateSequence(row.key);
      setLastAction(`${row.key} activated.`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Activate failed");
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDeactivate(row: SequenceRow) {
    if (!confirm(`Deactivate "${row.key}"? No further sends will go out for it until reactivated.`)) return;
    setBusyKey(row.key);
    setActionError(null);
    setLastAction(null);
    try {
      await deactivateSequence(row.key);
      setLastAction(`${row.key} deactivated.`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Deactivate failed");
    } finally {
      setBusyKey(null);
    }
  }

  if (loading) return <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading…</p>;
  if (loadError) return <p className="text-[11px] font-mono" style={{ color: "#e05d5d" }}>Cloud Decoded feed: {loadError}</p>;

  return (
    <div>
      <p className="text-[10px] font-mono mb-3" style={{ color: "#5b6673" }}>
        No endpoint reports current active/inactive state — this shows approval progress only.
      </p>
      {actionError && <p className="text-[11px] font-mono mb-2" style={{ color: "#e05d5d" }}>{actionError}</p>}
      {lastAction && <p className="text-[11px] font-mono mb-2" style={{ color: "#6fce8f" }}>{lastAction}</p>}
      <div className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.key} className="flex items-center gap-3 px-3 py-2 flex-wrap" style={{ border: "1px solid #1c222b", borderRadius: 8 }}>
            <span className="text-[12px] font-mono font-semibold" style={{ color: "#eef2f5" }}>{row.key}</span>
            <span className="text-[11px] font-mono" style={{ color: row.approvedSteps === row.totalSteps ? "#6fce8f" : "#e8963f" }}>
              {row.approvedSteps}/{row.totalSteps} steps approved
            </span>
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={() => handleActivate(row)}
                disabled={busyKey === row.key}
                className="px-3 py-1 rounded-[6px] text-[11px] font-mono font-semibold"
                style={{ border: "1px solid #6fce8f", color: "#6fce8f", backgroundColor: "#6fce8f1a" }}
              >
                Activate
              </button>
              <button
                onClick={() => handleDeactivate(row)}
                disabled={busyKey === row.key}
                className="px-3 py-1 rounded-[6px] text-[11px] font-mono font-semibold"
                style={{ border: "1px solid #9aa2ab", color: "#9aa2ab", backgroundColor: "transparent" }}
              >
                Deactivate
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
