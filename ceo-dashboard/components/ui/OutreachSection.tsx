"use client";

import { useCallback, useEffect, useState } from "react";
import { BuyerResearchLane } from "@/components/ui/BuyerResearchLane";

// THE single outreach surface (Kelvin's decision 3, 2026-10-05). The MSE
// dashboard's own Outreach page is retired to read-only; there is deliberately
// no second approval queue anywhere, because the one that existed rendered
// "Unknown / no contact on file" for all 11 drafts and routed every approval
// to a status nothing polled.
//
// Four lanes in a fixed order, matching the actual flow:
//   (a) Find the Buyer   -- a qualified company with no named buyer yet
//   (b) Approve Drafts   -- copy waiting on a human; nothing sends before this
//   (c) Ready to Paste   -- approved LinkedIn-track copy, with copy buttons
//   (d) Conversations    -- someone replied; how far it went
//
// Cards are composed server-side (/marketing/outreach/drafts) rather than
// assembled from a client-side join, which is the specific mistake that lost
// the contact on the old page.

type Grade = "valid" | "risky" | "invalid" | "unknown" | null;

type Card = {
  sequence_id: string;
  status: string;
  lead_source: string;
  product: string | null;
  lead_id: string | null;
  company: string | null;
  domain: string | null;
  contact: {
    name: string | null;
    title: string | null;
    linkedin_url: string | null;
    email: string | null;
    email_grade: Grade;
    contact_status: string | null;
  };
  route: string | null;
  signal: {
    role: string | null;
    posting_url: string | null;
    posting_age_days: number | null;
    open_role_count: number | null;
    stack: string[];
  };
  scores: { fit: number | null; intent: number | null };
  why: string[];
  touches: Record<string, string>;
};

type Conversation = {
  conversation_id: string;
  lead_id: string | null;
  product: string | null;
  company: string | null;
  contact: { name: string | null; title: string | null; email: string | null; linkedin_url: string | null };
  stage: string;
  lost_reason: string | null;
};

type Summary = {
  awaiting_buyer: number;
  awaiting_approval: number;
  sends_today: number;
  daily_send_cap: number;
  ready_to_paste: number;
  replies_this_week: number | null;
  parked_awaiting_contact: number;
};

const GRADE_COLOR: Record<string, string> = {
  valid: "#6fce8f",
  risky: "#e8963f",
  invalid: "#e05d5d",
  unknown: "#9aa2ab",
};

const STAGES = ["replied", "call_booked", "proposal_sent", "won", "lost"] as const;
const STAGE_LABEL: Record<string, string> = {
  replied: "Replied",
  call_booked: "Call booked",
  proposal_sent: "Proposal",
  won: "Won",
  lost: "Lost",
};

async function call(path: string, init?: RequestInit) {
  const res = await fetch(path, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.detail ? JSON.stringify(body.detail) : `HTTP ${res.status}`);
  return body;
}

function Counter({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="px-3 py-2 rounded-[10px]" style={{ background: "#10151b", border: "1px solid #1c222b" }}>
      <div className="text-[10px] font-mono uppercase tracking-wider" style={{ color: "#8b96a3" }}>
        {label}
      </div>
      <div className="text-[18px] font-bold" style={{ color: tone ?? "#eef2f5" }}>
        {value}
      </div>
    </div>
  );
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="px-1.5 py-0.5 rounded-[5px] text-[9.5px] font-mono"
      style={{ background: `${color}22`, color }}
    >
      {text}
    </span>
  );
}

export function OutreachSection() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [drafts, setDrafts] = useState<Card[]>([]);
  const [ready, setReady] = useState<Card[]>([]);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, d, r, c] = await Promise.all([
        call("/api/outreach/summary"),
        call("/api/outreach/drafts"),
        call("/api/outreach/ready-to-paste"),
        call("/api/outreach/conversations"),
      ]);
      setSummary(s);
      setDrafts(d.drafts ?? []);
      setReady(r.ready ?? []);
      setConvs(c.conversations ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the outreach lanes");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    try {
      await fn();
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  function copy(text: string, key: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      window.setTimeout(() => setCopied(null), 1500);
    });
  }

  return (
    <div id="outreach" className="space-y-4 min-w-0">
      {/* Header counters -- same numbers as the 8am digest, from the same
          endpoint, so the email and this header cannot disagree. */}
      <div className="flex flex-wrap gap-2">
        <Counter label="awaiting buyer" value={String(summary?.awaiting_buyer ?? "—")} />
        <Counter
          label="awaiting approval"
          value={String(summary?.awaiting_approval ?? "—")}
          tone={summary && summary.awaiting_approval > 0 ? "#e8963f" : undefined}
        />
        <Counter
          label="sends today"
          value={summary ? `${summary.sends_today} / ${summary.daily_send_cap}` : "—"}
        />
        <Counter label="ready to paste" value={String(summary?.ready_to_paste ?? "—")} />
        {/* null means NOT MEASURED -- rendering 0 would claim nobody replied. */}
        <Counter
          label="replies this week"
          value={summary ? (summary.replies_this_week == null ? "not measured" : String(summary.replies_this_week)) : "—"}
          tone={summary?.replies_this_week == null ? "#5b6673" : "#6fce8f"}
        />
      </div>

      {error && (
        <div
          className="px-3 py-2 rounded-[10px] text-[12px]"
          style={{ background: "#e05d5d22", color: "#e05d5d", border: "1px solid #e05d5d" }}
        >
          {error}
        </div>
      )}

      {/* ── (a) Find the Buyer ─────────────────────────────────────────── */}
      <div>
        <div className="text-[13px] font-bold mb-2" style={{ color: "#c7cfd6" }}>
          a · Find the Buyer
          {summary?.parked_awaiting_contact ? (
            <span className="ml-2 text-[11px] font-normal" style={{ color: "#8b96a3" }}>
              {summary.parked_awaiting_contact} draft(s) parked until a buyer is named
            </span>
          ) : null}
        </div>
        <BuyerResearchLane />
      </div>

      {/* ── (b) Approve Drafts ─────────────────────────────────────────── */}
      <div>
        <div className="text-[13px] font-bold mb-2" style={{ color: "#c7cfd6" }}>
          b · Approve Drafts{" "}
          <span className="text-[11px] font-normal" style={{ color: "#8b96a3" }}>
            nothing sends until you approve
          </span>
        </div>
        {drafts.length === 0 ? (
          <div className="text-[12px]" style={{ color: "#5b6673" }}>
            No drafts awaiting approval.
          </div>
        ) : (
          <div className="space-y-3">
            {drafts.map((d) => {
              const grade = d.contact.email_grade ?? "unknown";
              const edit = edits[d.sequence_id] ?? {};
              return (
                <div
                  key={d.sequence_id}
                  className="p-4 rounded-[14px] min-w-0"
                  style={{ background: "#141a22", border: "1px solid #1c222b", borderLeft: "3px solid #e8963f" }}
                >
                  <div className="flex flex-wrap items-center gap-2 mb-1 min-w-0">
                    {d.product && <Badge text={d.product} color="#7ea6f5" />}
                    <span className="text-[14px] font-bold truncate" style={{ color: "#eef2f5" }}>
                      {d.company ?? "—"}
                    </span>
                    {d.route && (
                      <Badge
                        text={d.route === "outbound_email" ? "EMAIL" : "LINKEDIN"}
                        color={d.route === "outbound_email" ? "#6fce8f" : "#e8963f"}
                      />
                    )}
                  </div>

                  <div className="text-[12px] mb-1" style={{ color: "#aab4bd" }}>
                    {d.contact.name ?? "no contact"}
                    {d.contact.title ? ` · ${d.contact.title}` : ""}
                  </div>

                  <div className="text-[11px] font-mono mb-2 flex flex-wrap gap-x-3 gap-y-1" style={{ color: "#5b6673" }}>
                    {d.contact.linkedin_url && (
                      <a href={d.contact.linkedin_url} target="_blank" rel="noreferrer" style={{ color: "#7ea6f5" }}>
                        linkedin
                      </a>
                    )}
                    {d.contact.email && (
                      <span>
                        {d.contact.email}{" "}
                        <Badge text={grade} color={GRADE_COLOR[grade] ?? "#9aa2ab"} />
                      </span>
                    )}
                    <span>
                      fit {d.scores.fit ?? "—"} · intent {d.scores.intent ?? "—"}
                    </span>
                  </div>

                  <div className="text-[11px] mb-2" style={{ color: "#8b96a3" }}>
                    signal:{" "}
                    {d.signal.posting_url ? (
                      <a href={d.signal.posting_url} target="_blank" rel="noreferrer" style={{ color: "#7ea6f5" }}>
                        {d.signal.role ?? "posting"}
                      </a>
                    ) : (
                      d.signal.role ?? "—"
                    )}
                    {d.signal.posting_age_days != null ? ` · posted ${d.signal.posting_age_days}d ago` : " · age unknown"}
                    {d.signal.open_role_count != null ? ` · ${d.signal.open_role_count} open roles` : ""}
                  </div>

                  {Object.entries(d.touches).map(([k, v]) => (
                    <div key={k} className="mb-2">
                      <div className="text-[10px] font-mono mb-1" style={{ color: "#5b6673" }}>
                        {k}
                      </div>
                      <textarea
                        className="w-full text-[12px] p-2 rounded-[8px] font-sans"
                        rows={Math.min(8, Math.ceil((edit[k] ?? v).length / 90) + 1)}
                        style={{ background: "#10151b", border: "1px solid #1c222b", color: "#eef2f5" }}
                        value={edit[k] ?? v}
                        onChange={(e) =>
                          setEdits((prev) => ({
                            ...prev,
                            [d.sequence_id]: { ...(prev[d.sequence_id] ?? {}), [k]: e.target.value },
                          }))
                        }
                      />
                    </div>
                  ))}

                  <div className="flex flex-wrap gap-2 mt-2">
                    <button
                      disabled={busy === d.sequence_id || Object.keys(edit).length === 0}
                      onClick={() =>
                        act(d.sequence_id, () =>
                          call(`/api/outreach/drafts/${d.sequence_id}/edit`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(edit),
                          })
                        )
                      }
                      className="px-3 py-1.5 rounded-[6px] text-[12px]"
                      style={{
                        background: "transparent",
                        border: "1px solid #7ea6f5",
                        color: "#7ea6f5",
                        opacity: busy === d.sequence_id || Object.keys(edit).length === 0 ? 0.4 : 1,
                      }}
                    >
                      Save edits
                    </button>
                    <button
                      disabled={busy === d.sequence_id}
                      onClick={() =>
                        act(d.sequence_id, async () => {
                          if (Object.keys(edit).length > 0) {
                            await call(`/api/outreach/drafts/${d.sequence_id}/edit`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(edit),
                            });
                          }
                          return call(`/api/outreach-approve/${d.sequence_id}/approve`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ resolved_by: "ceo-decoded" }),
                          });
                        })
                      }
                      className="px-3 py-1.5 rounded-[6px] text-[12px]"
                      style={{ background: "transparent", border: "1px solid #5eead4", color: "#5eead4" }}
                    >
                      Approve
                    </button>
                    <button
                      disabled={busy === d.sequence_id}
                      onClick={() => {
                        const reason = window.prompt("Reject reason?");
                        if (!reason) return;
                        void act(d.sequence_id, () =>
                          call(`/api/outreach-approve/${d.sequence_id}/reject`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ resolved_by: "ceo-decoded", reason }),
                          })
                        );
                      }}
                      className="px-3 py-1.5 rounded-[6px] text-[12px]"
                      style={{ background: "transparent", border: "1px solid #9aa2ab", color: "#9aa2ab" }}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── (c) Ready to Paste ─────────────────────────────────────────── */}
      <div>
        <div className="text-[13px] font-bold mb-2" style={{ color: "#c7cfd6" }}>
          c · Ready to Paste{" "}
          <span className="text-[11px] font-normal" style={{ color: "#8b96a3" }}>
            approved LinkedIn-track copy
          </span>
        </div>
        {ready.length === 0 ? (
          <div className="text-[12px]" style={{ color: "#5b6673" }}>
            Nothing approved for manual sending.
          </div>
        ) : (
          <div className="space-y-3">
            {ready.map((r) => (
              <div
                key={r.sequence_id}
                className="p-4 rounded-[14px] min-w-0"
                style={{ background: "#141a22", border: "1px solid #1c222b", borderLeft: "3px solid #5eead4" }}
              >
                <div className="flex flex-wrap items-center gap-2 mb-1 min-w-0">
                  <span className="text-[14px] font-bold truncate" style={{ color: "#eef2f5" }}>
                    {r.company ?? "—"}
                  </span>
                  <span className="text-[12px]" style={{ color: "#aab4bd" }}>
                    {r.contact.name}
                    {r.contact.title ? ` · ${r.contact.title}` : ""}
                  </span>
                  {r.contact.linkedin_url && (
                    <a href={r.contact.linkedin_url} target="_blank" rel="noreferrer"
                       className="text-[11px] font-mono" style={{ color: "#7ea6f5" }}>
                      open profile
                    </a>
                  )}
                </div>
                {Object.entries(r.touches).map(([k, v]) => (
                  <div key={k} className="flex gap-2 items-start mb-2 min-w-0">
                    <div className="flex-1 min-w-0 text-[12px] p-2 rounded-[8px]"
                         style={{ background: "#10151b", border: "1px solid #1c222b", color: "#eef2f5" }}>
                      {v}
                    </div>
                    <button
                      onClick={() => copy(v, `${r.sequence_id}-${k}`)}
                      className="px-2 py-1 rounded-[6px] text-[11px] shrink-0"
                      style={{ background: "transparent", border: "1px solid #5eead4", color: "#5eead4" }}
                    >
                      {copied === `${r.sequence_id}-${k}` ? "copied" : `copy ${k}`}
                    </button>
                  </div>
                ))}
                <div className="flex flex-wrap gap-2 mt-2">
                  {(["sent", "accepted", "replied"] as const).map((ev) => (
                    <button
                      key={ev}
                      disabled={busy === r.sequence_id}
                      onClick={() =>
                        act(r.sequence_id, () =>
                          call(`/api/outreach/ready-to-paste/${r.sequence_id}/mark`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ event: ev }),
                          })
                        )
                      }
                      className="px-3 py-1.5 rounded-[6px] text-[12px]"
                      style={{
                        background: "transparent",
                        border: `1px solid ${ev === "replied" ? "#6fce8f" : "#9aa2ab"}`,
                        color: ev === "replied" ? "#6fce8f" : "#9aa2ab",
                      }}
                    >
                      mark {ev}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── (d) Conversations ──────────────────────────────────────────── */}
      <div>
        <div className="text-[13px] font-bold mb-2" style={{ color: "#c7cfd6" }}>
          d · Conversations{" "}
          <span className="text-[11px] font-normal" style={{ color: "#8b96a3" }}>
            marking replied stops the remaining touches
          </span>
        </div>
        {convs.length === 0 ? (
          <div className="text-[12px]" style={{ color: "#5b6673" }}>
            No replies recorded yet.
          </div>
        ) : (
          <div className="space-y-2">
            {convs.map((c) => (
              <div
                key={c.conversation_id}
                className="p-3 rounded-[12px] flex flex-wrap items-center gap-2 min-w-0"
                style={{ background: "#10151b", border: "1px solid #1c222b" }}
              >
                <span className="text-[13px] font-bold truncate" style={{ color: "#eef2f5" }}>
                  {c.company ?? "—"}
                </span>
                <span className="text-[11px] truncate" style={{ color: "#8b96a3" }}>
                  {c.contact.name}
                  {c.contact.title ? ` · ${c.contact.title}` : ""}
                </span>
                <Badge text={STAGE_LABEL[c.stage] ?? c.stage} color={c.stage === "won" ? "#6fce8f" : c.stage === "lost" ? "#e05d5d" : "#7ea6f5"} />
                {c.lost_reason && (
                  <span className="text-[11px]" style={{ color: "#5b6673" }}>
                    {c.lost_reason}
                  </span>
                )}
                <div className="flex flex-wrap gap-1 ml-auto">
                  {STAGES.filter((s) => s !== c.stage).map((s) => (
                    <button
                      key={s}
                      disabled={!c.lead_id || busy === c.conversation_id}
                      onClick={() => {
                        const reason = s === "lost" ? window.prompt("Lost reason?") ?? undefined : undefined;
                        void act(c.conversation_id, () =>
                          call(`/api/outreach/conversations/${c.lead_id}/stage`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ stage: s, lost_reason: reason }),
                          })
                        );
                      }}
                      className="px-2 py-1 rounded-[5px] text-[10.5px] font-mono"
                      style={{
                        background: "transparent",
                        border: "1px solid #1c222b",
                        color: s === "won" ? "#6fce8f" : s === "lost" ? "#e05d5d" : "#8b96a3",
                      }}
                    >
                      {STAGE_LABEL[s]}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
