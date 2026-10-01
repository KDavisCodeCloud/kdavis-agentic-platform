"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBuyerResearchTasks, saveBuyerContact, skipBuyerResearchTask } from "@/lib/api";
import type { BuyerResearchTask } from "@/lib/types";

// Buyer-research lane (decision 5b, 2026-10-01).
//
// Scraper v2's two-stage model qualifies a COMPANY without needing a contact:
// matching role + resolved domain + exclusions pass + size proxy in band. The
// 2026-10-01 runs produced five such companies where neither the free sources
// (JD-named hiring manager, /team, /about, /leadership) nor a Brave query could
// name a buyer. Rather than leave them parked, each becomes one task here.
//
// Saving a pasted profile creates the contact and triggers email pattern +
// SMTP + catch-all grading on the backend. Only a 'valid' grade can ever reach
// MKT-O5, and every send still passes HITL.
//
// Design tokens are the CEO Decoded set from CLAUDE.md -- card #141a22, tile
// #10151b, border #1c222b, mint #5eead4, mono for data. Maximum density.

const CARD = "#141a22";
const TILE = "#10151b";
const BORDER = "#1c222b";
const MINT = "#5eead4";
const TEXT = "#eef2f5";
const LABEL = "#c7cfd6";
const MUTED = "#5b6673";
const SECONDARY = "#aab4bd";
const AMBER = "#e8963f";

type Draft = { url: string; name: string; title: string };

const EMPTY_DRAFT: Draft = { url: "", name: "", title: "" };

function scoreColor(value: number | null): string {
  if (value === null) return MUTED;
  if (value >= 0.7) return "#6fce8f";
  if (value >= 0.5) return MINT;
  return AMBER;
}

export function BuyerResearchLane() {
  const [tasks, setTasks] = useState<BuyerResearchTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notices, setNotices] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTasks(await fetchBuyerResearchTasks());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const draftFor = (id: string): Draft => drafts[id] ?? EMPTY_DRAFT;

  const setDraft = (id: string, patch: Partial<Draft>) =>
    setDrafts((prev) => ({ ...prev, [id]: { ...(prev[id] ?? EMPTY_DRAFT), ...patch } }));

  async function onSave(task: BuyerResearchTask) {
    const draft = draftFor(task.lead_id);
    setRowErrors((p) => ({ ...p, [task.lead_id]: "" }));

    // Validated here as well as on the backend so a typo is caught before a
    // round trip. A /company/ URL is the common paste mistake.
    if (!/^https?:\/\/([a-z]{2,3}\.)?linkedin\.com\/in\/[\w\-%./]+\/?$/i.test(draft.url.trim())) {
      setRowErrors((p) => ({
        ...p,
        [task.lead_id]: "Needs a personal profile URL — linkedin.com/in/… (not /company/…)",
      }));
      return;
    }
    if (!draft.name.trim() || !draft.title.trim()) {
      setRowErrors((p) => ({ ...p, [task.lead_id]: "Name and title are both required" }));
      return;
    }

    setBusyId(task.lead_id);
    try {
      const result = await saveBuyerContact(task.lead_id, {
        linkedin_url: draft.url.trim(),
        name: draft.name.trim(),
        title: draft.title.trim(),
      });
      setNotices((p) => ({
        ...p,
        [task.lead_id]: `Saved — now in the MKT-O2 queue. Email grading: ${result.email_grading}.`,
      }));
      // Drop it from the lane; it is no longer awaiting a contact.
      setTasks((prev) => prev.filter((t) => t.lead_id !== task.lead_id));
    } catch (err) {
      setRowErrors((p) => ({
        ...p,
        [task.lead_id]: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setBusyId(null);
    }
  }

  async function onSkip(task: BuyerResearchTask) {
    setBusyId(task.lead_id);
    try {
      await skipBuyerResearchTask(task.lead_id);
      setTasks((prev) => prev.filter((t) => t.lead_id !== task.lead_id));
    } catch (err) {
      setRowErrors((p) => ({
        ...p,
        [task.lead_id]: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section
      style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 14, padding: 20 }}
    >
      <div className="flex items-baseline justify-between" style={{ marginBottom: 14 }}>
        <h2 style={{ fontSize: 13, fontWeight: 700, color: LABEL }}>
          Find the buyer{" "}
          <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 11, color: MUTED }}>
            {loading ? "" : `${tasks.length} compan${tasks.length === 1 ? "y" : "ies"} qualified, no contact yet`}
          </span>
        </h2>
        <button
          onClick={() => void load()}
          style={{
            fontSize: 11, fontFamily: "var(--font-mono, monospace)", color: MINT,
            border: `1px solid ${MINT}55`, borderRadius: 6, padding: "4px 10px", background: "transparent",
          }}
        >
          refresh
        </button>
      </div>

      {error && (
        <p
          style={{
            fontSize: 12, color: "#e05d5d", background: "#e05d5d14",
            border: "1px solid #e05d5d44", borderRadius: 8, padding: "8px 10px", marginBottom: 12,
          }}
        >
          {error}
        </p>
      )}

      {loading && <p style={{ fontSize: 12, color: MUTED }}>Loading…</p>}

      {!loading && !error && tasks.length === 0 && (
        <p style={{ fontSize: 12, color: MINT }}>
          Nothing waiting — every qualified company has a contact.
        </p>
      )}

      <div className="flex flex-col" style={{ gap: 12 }}>
        {tasks.map((task) => {
          const draft = draftFor(task.lead_id);
          const busy = busyId === task.lead_id;
          return (
            <article
              key={task.lead_id}
              style={{ background: TILE, border: `1px solid ${BORDER}`, borderRadius: 12, padding: 14 }}
            >
              <div className="flex flex-wrap items-baseline" style={{ gap: 8 }}>
                <h3 style={{ fontSize: 14, fontWeight: 700, color: TEXT, minWidth: 0 }}>
                  {task.headline}
                </h3>
                {task.domain && (
                  <a
                    href={`https://${task.domain}`}
                    target="_blank"
                    rel="noreferrer noopener"
                    style={{
                      fontFamily: "var(--font-mono, monospace)", fontSize: 11, color: MINT,
                      textDecoration: "none",
                    }}
                  >
                    {task.domain}
                  </a>
                )}
                {task.domain_source && (
                  <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 9.5, color: MUTED }}>
                    via {task.domain_source}
                  </span>
                )}
              </div>

              {/* Why this company qualified -- the lane has to be answerable
                  without opening another tab. */}
              <dl
                className="flex flex-wrap"
                style={{ gap: "4px 18px", margin: "8px 0", fontSize: 11.5, color: SECONDARY }}
              >
                <div>
                  <dt style={{ display: "inline", color: MUTED }}>hiring: </dt>
                  <dd style={{ display: "inline", color: TEXT }}>
                    {task.role_signal.posting_url ? (
                      <a
                        href={task.role_signal.posting_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        style={{ color: TEXT }}
                      >
                        {task.role_signal.title ?? "role not named"}
                      </a>
                    ) : (
                      task.role_signal.title ?? "role not named"
                    )}
                  </dd>
                </div>
                <div>
                  <dt style={{ display: "inline", color: MUTED }}>matching roles: </dt>
                  <dd
                    style={{
                      display: "inline", fontFamily: "var(--font-mono, monospace)", color: TEXT,
                    }}
                  >
                    {task.role_signal.matching_roles ?? "—"}
                    {task.role_signal.open_roles_on_board != null &&
                      ` of ${task.role_signal.open_roles_on_board} open`}
                  </dd>
                </div>
                <div>
                  <dt style={{ display: "inline", color: MUTED }}>fit / intent: </dt>
                  <dd style={{ display: "inline", fontFamily: "var(--font-mono, monospace)" }}>
                    <span style={{ color: scoreColor(task.scores.fit) }}>
                      {task.scores.fit ?? "—"}
                    </span>
                    <span style={{ color: MUTED }}> / </span>
                    <span style={{ color: scoreColor(task.scores.intent) }}>
                      {task.scores.intent ?? "—"}
                    </span>
                  </dd>
                </div>
                {task.location && (
                  <div>
                    <dt style={{ display: "inline", color: MUTED }}>location: </dt>
                    <dd style={{ display: "inline" }}>{task.location}</dd>
                  </div>
                )}
                {task.automated_attempts > 0 && (
                  <div>
                    <dt style={{ display: "inline", color: MUTED }}>auto attempts: </dt>
                    <dd
                      style={{
                        display: "inline", fontFamily: "var(--font-mono, monospace)", color: AMBER,
                      }}
                    >
                      {task.automated_attempts}
                    </dd>
                  </div>
                )}
              </dl>

              {task.role_signal.stack.length > 0 && (
                <div className="flex flex-wrap" style={{ gap: 4, marginBottom: 8 }}>
                  {task.role_signal.stack.map((tech) => (
                    <span
                      key={tech}
                      style={{
                        fontFamily: "var(--font-mono, monospace)", fontSize: 9.5,
                        color: MINT, background: `${MINT}1a`, borderRadius: 5, padding: "2px 6px",
                      }}
                    >
                      {tech}
                    </span>
                  ))}
                </div>
              )}

              <p style={{ fontSize: 11, color: MUTED, marginBottom: 10 }}>
                Look for:{" "}
                <span style={{ color: SECONDARY }}>{task.target_titles.join(" · ")}</span>
              </p>

              {/* Paste field. Three inputs, all required -- a profile URL with
                  no name and title leaves the lead unaddressable, and a name
                  with no title would let MKT-O2 assert a role nobody verified. */}
              <div className="flex flex-wrap" style={{ gap: 8 }}>
                <input
                  value={draft.url}
                  onChange={(e) => setDraft(task.lead_id, { url: e.target.value })}
                  placeholder="https://www.linkedin.com/in/…"
                  aria-label={`LinkedIn profile URL for ${task.company ?? "this company"}`}
                  style={{
                    flex: "2 1 260px", minWidth: 0, fontSize: 12,
                    fontFamily: "var(--font-mono, monospace)", color: TEXT,
                    background: CARD, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "7px 9px",
                  }}
                />
                <input
                  value={draft.name}
                  onChange={(e) => setDraft(task.lead_id, { name: e.target.value })}
                  placeholder="Full name"
                  aria-label={`Contact name at ${task.company ?? "this company"}`}
                  style={{
                    flex: "1 1 140px", minWidth: 0, fontSize: 12, color: TEXT,
                    background: CARD, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "7px 9px",
                  }}
                />
                <input
                  value={draft.title}
                  onChange={(e) => setDraft(task.lead_id, { title: e.target.value })}
                  placeholder="Title"
                  aria-label={`Contact title at ${task.company ?? "this company"}`}
                  style={{
                    flex: "1 1 140px", minWidth: 0, fontSize: 12, color: TEXT,
                    background: CARD, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "7px 9px",
                  }}
                />
                <button
                  onClick={() => void onSave(task)}
                  disabled={busy}
                  style={{
                    fontSize: 12, fontWeight: 600, color: busy ? MUTED : "#0b0e13",
                    background: busy ? BORDER : MINT, border: "none", borderRadius: 8,
                    padding: "7px 14px", minHeight: 36,
                  }}
                >
                  {busy ? "Saving…" : "Save contact"}
                </button>
                <button
                  onClick={() => void onSkip(task)}
                  disabled={busy}
                  style={{
                    fontSize: 12, color: SECONDARY, background: "transparent",
                    border: `1px solid ${BORDER}`, borderRadius: 8, padding: "7px 12px", minHeight: 36,
                  }}
                >
                  Skip
                </button>
              </div>

              {rowErrors[task.lead_id] && (
                <p style={{ fontSize: 11, color: "#e05d5d", marginTop: 8 }}>
                  {rowErrors[task.lead_id]}
                </p>
              )}
              {notices[task.lead_id] && (
                <p style={{ fontSize: 11, color: "#6fce8f", marginTop: 8 }}>
                  {notices[task.lead_id]}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
