"use client";

import { useCallback, useEffect, useState } from "react";
import { batchApproveLinkedInQueue, fetchLinkedInQueue, updateLinkedInQueueRow } from "@/lib/api";
import { AssetThumbnail } from "./AssetThumbnail";
import { StatusBadge } from "./StatusBadge";
import type { LinkedInQueuePost } from "@/lib/types";

function currentBatchMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function formatScheduledFor(iso: string | null): string {
  if (!iso) return "unscheduled";
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", timeZone: "America/Phoenix",
  }) + " AZ";
}

// datetime-local inputs carry no timezone -- their value is just wall-clock
// digits. These two convert between that wall-clock string and a UTC ISO
// instant, always anchored to Arizona time (UTC-7, no DST, year-round) so
// what the owner picks is what actually gets stored and redisplayed.
function isoToArizonaLocalInput(iso: string | null): string {
  if (!iso) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Phoenix",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

function arizonaLocalInputToISO(localDateTime: string): string {
  return new Date(`${localDateTime}:00-07:00`).toISOString();
}

function imageStatusLabel(post: LinkedInQueuePost): string {
  if (post.format === "document_carousel") return "carousel (no single image)";
  const brief = post.image_brief;
  if (!brief) return "no image";
  if (brief.image_path) {
    const source = brief.credit_line ? brief.credit_line : "original / Gemini-generated";
    return `🖼 ${source} — ${brief.image_path}`;
  }
  if (brief.generation_available) return "⏳ image not generated yet (run monthly_batch.sh Step 1.5)";
  return "no image match";
}

export function LinkedInBatchReview() {
  const [batchMonth, setBatchMonth] = useState(currentBatchMonth());
  const [posts, setPosts] = useState<LinkedInQueuePost[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [rescheduleDrafts, setRescheduleDrafts] = useState<Record<string, string>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setActionError(null);
    try {
      const rows = await fetchLinkedInQueue({ batchMonth });
      setPosts(rows);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to load batch");
    } finally {
      setLoading(false);
    }
  }, [batchMonth]);

  useEffect(() => {
    load();
  }, [load]);

  async function review(queueId: string, status: "approved" | "rejected") {
    setActionError(null);
    try {
      await updateLinkedInQueueRow(queueId, { status });
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function reschedule(queueId: string) {
    const localDateTime = rescheduleDrafts[queueId];
    if (!localDateTime) return;
    setActionError(null);
    try {
      await updateLinkedInQueueRow(queueId, { scheduled_for: arizonaLocalInputToISO(localDateTime) });
      setRescheduleDrafts((prev) => {
        const next = { ...prev };
        delete next[queueId];
        return next;
      });
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Reschedule failed");
    }
  }

  // "Append" — adds/updates a reviewer note on a post independently of an
  // approve/reject decision (e.g. "approve, but flag the second sentence"
  // or a reason for rejecting). Never overwrites status.
  async function appendNote(queueId: string) {
    const note = noteDrafts[queueId];
    if (!note || !note.trim()) return;
    setActionError(null);
    try {
      await updateLinkedInQueueRow(queueId, { hitl_notes: note.trim() });
      setNoteDrafts((prev) => ({ ...prev, [queueId]: "" }));
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Adding note failed");
    }
  }

  async function approveBatch() {
    setApproving(true);
    setActionError(null);
    try {
      const result = await batchApproveLinkedInQueue(batchMonth);
      await load();
      if (result.approved_count === 0) {
        setActionError("No pending_review posts left to approve in this batch.");
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Batch approve failed");
    } finally {
      setApproving(false);
    }
  }

  const pendingCount = posts.filter((p) => p.status === "pending_review").length;
  const approvedCount = posts.filter((p) => p.status === "approved").length;
  const rejectedCount = posts.filter((p) => p.status === "rejected").length;
  const publishedCount = posts.filter((p) => p.status === "published").length;

  // A decided post (approved/rejected/published) stays in `posts` for the
  // counts above, but drops out of the reviewable list below the moment a
  // decision is made -- the queue is for what still needs a decision, not
  // a running history of every post ever drafted this month.
  const reviewablePosts = posts.filter((p) => p.status === "pending_review");

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <input
            type="month"
            value={batchMonth}
            onChange={(e) => setBatchMonth(e.target.value)}
            className="font-mono px-2 py-1 rounded-[6px]"
            style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", minHeight: 44, fontSize: 16 }}
          />
          <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
            {posts.length} posts · {pendingCount} awaiting review · {approvedCount} approved · {rejectedCount} rejected · {publishedCount} published
          </span>
        </div>
        <button
          onClick={approveBatch}
          disabled={approving || pendingCount === 0}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors shrink-0"
          style={{
            border: "1px solid #5eead4",
            color: pendingCount === 0 ? "#3a4250" : "#5eead4",
            backgroundColor: "transparent",
            opacity: approving ? 0.6 : 1,
            minHeight: 44,
          }}
          title="Approves every post still awaiting review in this batch_month. Posts already approved or rejected individually are left as-is — this is not all-or-nothing."
        >
          {approving ? "Approving…" : `Approve all pending (${pendingCount})`}
        </button>
      </div>

      {actionError && (
        <p className="text-[11px] font-mono mb-3" style={{ color: "#e05d5d" }}>{actionError}</p>
      )}

      {loading ? (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading batch…</p>
      ) : posts.length === 0 ? (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          No posts for {batchMonth} yet — run scripts/monthly_batch.sh to generate this month's batch.
        </p>
      ) : reviewablePosts.length === 0 ? (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          All {posts.length} posts in this batch have been reviewed — {approvedCount} approved, {rejectedCount} rejected, {publishedCount} published.
        </p>
      ) : (
        <div className="space-y-0">
          {reviewablePosts.map((post) => (
            <div key={post.id} className="py-3 min-w-0 flex gap-3" style={{ borderTop: "1px solid #1c222b" }}>
              {post.image_brief?.image_path && (
                <AssetThumbnail imagePath={post.image_brief.image_path} alt={post.topic ?? "post image"} />
              )}

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1 min-w-0 flex-wrap">
                  <span className="text-[12.5px] font-semibold truncate-text min-w-0" style={{ color: "#eef2f5" }}>
                    {post.topic || "(untitled)"}
                  </span>
                  <span className="text-[10.5px] font-mono shrink-0" style={{ color: "#5b6673" }}>
                    {post.pillar_name ?? `Pillar ${post.pillar ?? "?"}`}
                  </span>
                  <StatusBadge status={post.status} />
                  <span className="text-[10.5px] font-mono shrink-0" style={{ color: "#8b96a3" }}>
                    Tier {post.hitl_tier ?? "?"}
                  </span>
                </div>

                {expandedId === post.id ? (
                  <div className="mb-2">
                    {post.image_brief?.image_path && (
                      <div className="mb-2">
                        <AssetThumbnail imagePath={post.image_brief.image_path} alt={post.topic ?? "post image"} size={320} />
                      </div>
                    )}
                    <p className="text-[12px] whitespace-pre-wrap mb-2" style={{ color: "#eef2f5" }}>
                      {post.post_copy}
                    </p>
                    {post.hook_variants && post.hook_variants.length > 0 && (
                      <div className="mb-2">
                        <p className="text-[10px] font-mono uppercase mb-1" style={{ color: "#5b6673" }}>
                          Hook variants
                        </p>
                        <ul className="space-y-1">
                          {post.hook_variants.map((hook, i) => (
                            <li key={i} className="text-[11.5px]" style={{ color: "#aab4bd" }}>
                              {i + 1}. {hook}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-[11.5px] mb-1.5 truncate-text" style={{ color: "#aab4bd" }}>
                    {post.post_copy}
                  </p>
                )}

                <p className="text-[10.5px] font-mono mb-2" style={{ color: "#5b6673" }}>
                  {formatScheduledFor(post.scheduled_for)} · {imageStatusLabel(post)}
                </p>

                {post.hitl_notes && (
                  <p
                    className="text-[11px] mb-2 px-2.5 py-1.5 rounded-[6px]"
                    style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#e8963f" }}
                  >
                    📝 {post.hitl_notes}
                  </p>
                )}

                <div className="flex items-center gap-2 flex-wrap mb-2">
                  <button
                    onClick={() => setExpandedId(expandedId === post.id ? null : post.id)}
                    className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                    style={{ border: "1px solid #8b96a3", color: "#c7cfd6", backgroundColor: expandedId === post.id ? "#8b96a31a" : "transparent", minHeight: 44 }}
                  >
                    {expandedId === post.id ? "Collapse" : "Review"}
                  </button>
                </div>

                {post.status !== "published" && (
                  <div className="flex items-center gap-2 flex-wrap mb-2">
                    <button
                      onClick={() => review(post.id, "approved")}
                      disabled={post.status === "approved"}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                      style={{ border: "1px solid #5eead4", color: post.status === "approved" ? "#3a4250" : "#5eead4", backgroundColor: "transparent", minHeight: 44 }}
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => review(post.id, "rejected")}
                      disabled={post.status === "rejected"}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                      style={{ border: "1px solid #3a4250", color: post.status === "rejected" ? "#3a4250" : "#8b96a3", backgroundColor: "transparent", minHeight: 44 }}
                    >
                      Reject
                    </button>
                    {/* onChange fires per field the native picker commits (date,
                        then hour, then minute, ...), each one a distinct event --
                        saving on every onChange meant picking a date and time was
                        never one action and could commit a half-picked value. So
                        onChange only buffers into local draft state; the actual
                        save happens once, on OK. */}
                    <input
                      type="datetime-local"
                      value={rescheduleDrafts[post.id] ?? isoToArizonaLocalInput(post.scheduled_for)}
                      onChange={(e) => setRescheduleDrafts((prev) => ({ ...prev, [post.id]: e.target.value }))}
                      className="font-mono px-2 py-1 rounded-[6px]"
                      style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#aab4bd", minHeight: 44, fontSize: 16 }}
                      title="Reschedule this post (Arizona time)"
                    />
                    <button
                      onClick={() => reschedule(post.id)}
                      disabled={!rescheduleDrafts[post.id]}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                      style={{
                        border: "1px solid #5eead4",
                        color: rescheduleDrafts[post.id] ? "#5eead4" : "#3a4250",
                        backgroundColor: "transparent",
                        minHeight: 44,
                      }}
                      title="Save the picked date/time"
                    >
                      OK
                    </button>
                  </div>
                )}

                {post.status !== "published" && (
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      placeholder="Append a note (e.g. why you rejected this, or a tweak to make before it goes out)…"
                      value={noteDrafts[post.id] ?? ""}
                      onChange={(e) => setNoteDrafts((prev) => ({ ...prev, [post.id]: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") appendNote(post.id); }}
                      className="flex-1 min-w-0 px-2.5 py-1.5 rounded-[6px]"
                      style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", minHeight: 44, fontSize: 16 }}
                    />
                    <button
                      onClick={() => appendNote(post.id)}
                      disabled={!noteDrafts[post.id]?.trim()}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors shrink-0"
                      style={{ border: "1px solid #7ea6f5", color: noteDrafts[post.id]?.trim() ? "#7ea6f5" : "#3a4250", backgroundColor: "transparent", minHeight: 44 }}
                    >
                      Append
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
