"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchMSEContentQueue, updateMSEContentRow } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";
import type { MSEContentPost } from "@/lib/types";

const PLATFORM_LABEL: Record<MSEContentPost["platform"], string> = {
  reddit: "Reddit",
  facebook: "Facebook",
};

// MKT-V1's Reddit/Facebook community posts (mse_social_content,
// kdavis-microsaas-engine) previously dead-ended in Postgres — nothing
// ever read the table, no review step existed. This closes that gap:
// review → approve/reject → mark sent. "Sent" is a manual confirmation
// after a human physically posts the approved copy themselves — there is
// no automated Reddit/Facebook posting client yet (Meta Business
// verification and Reddit API credentials are both still open owner
// actions, not code problems), so this never claims to auto-publish.
export function MSEContentReview() {
  const [posts, setPosts] = useState<MSEContentPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("pending_review");

  const load = useCallback(async () => {
    setLoading(true);
    setActionError(null);
    try {
      const rows = await fetchMSEContentQueue(statusFilter ? { status: statusFilter } : {});
      setPosts(rows);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to load MSE content queue");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  async function review(id: string, status: "approved" | "rejected" | "sent") {
    setActionError(null);
    try {
      await updateMSEContentRow(id, { status });
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function appendNote(id: string) {
    const note = noteDrafts[id];
    if (!note || !note.trim()) return;
    setActionError(null);
    try {
      await updateMSEContentRow(id, { hitl_notes: note.trim() });
      setNoteDrafts((prev) => ({ ...prev, [id]: "" }));
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Adding note failed");
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="font-mono px-2 py-1 rounded-[6px]"
            style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", minHeight: 44, fontSize: 16 }}
          >
            <option value="pending_review">Needs review</option>
            <option value="approved">Approved — ready to send</option>
            <option value="rejected">Rejected</option>
            <option value="sent">Sent</option>
            <option value="">All</option>
          </select>
          <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
            {posts.length} post{posts.length === 1 ? "" : "s"}
          </span>
        </div>
      </div>

      {actionError && (
        <p className="text-[11px] font-mono mb-3" style={{ color: "#e05d5d" }}>{actionError}</p>
      )}

      {loading ? (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>Loading...</p>
      ) : posts.length === 0 ? (
        <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
          Nothing here — MKT-V1 hasn't produced any posts in this state yet.
        </p>
      ) : (
        <div className="space-y-0">
          {posts.map((post) => (
            <div key={post.id} className="py-3 min-w-0" style={{ borderTop: "1px solid #1c222b" }}>
              <div className="flex items-center gap-2 mb-1 min-w-0 flex-wrap">
                <span className="text-[10.5px] font-mono shrink-0 px-1.5 py-0.5 rounded-[5px]" style={{ backgroundColor: "#5b8def22", color: "#7ea6f5" }}>
                  {PLATFORM_LABEL[post.platform]}
                </span>
                {post.title && (
                  <span className="text-[12.5px] font-semibold truncate-text min-w-0" style={{ color: "#eef2f5" }}>
                    {post.title}
                  </span>
                )}
                <StatusBadge status={post.status} />
                <span className="text-[10.5px] font-mono shrink-0" style={{ color: "#5b6673" }}>
                  product {post.product_id.slice(0, 8)}
                </span>
              </div>

              {expandedId === post.id ? (
                <p className="text-[12px] whitespace-pre-wrap mb-2" style={{ color: "#eef2f5" }}>
                  {post.body}
                </p>
              ) : (
                <p className="text-[11.5px] mb-1.5 truncate-text" style={{ color: "#aab4bd" }}>
                  {post.body}
                </p>
              )}

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
                  {expandedId === post.id ? "Collapse" : "Read full post"}
                </button>

                {post.status === "pending_review" && (
                  <>
                    <button
                      onClick={() => review(post.id, "approved")}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                      style={{ border: "1px solid #5eead4", color: "#5eead4", backgroundColor: "transparent", minHeight: 44 }}
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => review(post.id, "rejected")}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                      style={{ border: "1px solid #3a4250", color: "#8b96a3", backgroundColor: "transparent", minHeight: 44 }}
                    >
                      Reject
                    </button>
                  </>
                )}

                {post.status === "approved" && (
                  <button
                    onClick={() => review(post.id, "sent")}
                    className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                    style={{ border: "1px solid #6fce8f", color: "#6fce8f", backgroundColor: "transparent", minHeight: 44 }}
                    title="Confirm you've posted this yourself on the platform — there's no automated posting yet"
                  >
                    Mark as sent
                  </button>
                )}
              </div>

              {post.status !== "sent" && (
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
          ))}
        </div>
      )}
    </div>
  );
}
