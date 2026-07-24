"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
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
    hour: "numeric", minute: "2-digit", timeZone: "America/New_York",
  }) + " ET";
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
  const supabase = createClient();
  const [batchMonth, setBatchMonth] = useState(currentBatchMonth());
  const [posts, setPosts] = useState<LinkedInQueuePost[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);

  const getToken = useCallback(async () => {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error("Not signed in");
    return session.access_token;
  }, [supabase]);

  const load = useCallback(async () => {
    setLoading(true);
    setActionError(null);
    try {
      const token = await getToken();
      const rows = await fetchLinkedInQueue(token, { batchMonth });
      setPosts(rows);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to load batch");
    } finally {
      setLoading(false);
    }
  }, [batchMonth, getToken]);

  useEffect(() => {
    load();
  }, [load]);

  async function review(queueId: string, status: "approved" | "rejected") {
    setActionError(null);
    try {
      const token = await getToken();
      await updateLinkedInQueueRow(token, queueId, { status });
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function reschedule(queueId: string, localDateTime: string) {
    if (!localDateTime) return;
    setActionError(null);
    try {
      const token = await getToken();
      await updateLinkedInQueueRow(token, queueId, { scheduled_for: new Date(localDateTime).toISOString() });
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Reschedule failed");
    }
  }

  async function approveBatch() {
    setApproving(true);
    setActionError(null);
    try {
      const token = await getToken();
      const result = await batchApproveLinkedInQueue(token, batchMonth);
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
  const publishedCount = posts.filter((p) => p.status === "published").length;

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <input
            type="month"
            value={batchMonth}
            onChange={(e) => setBatchMonth(e.target.value)}
            className="text-[11px] font-mono px-2 py-1 rounded-[6px]"
            style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5" }}
          />
          <span className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
            {posts.length} posts · {pendingCount} awaiting review · {approvedCount} approved · {publishedCount} published
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
          }}
        >
          {approving ? "Approving…" : `Approve entire batch (${pendingCount})`}
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
      ) : (
        <div className="space-y-0">
          {posts.map((post) => (
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

                <p className="text-[11.5px] mb-1.5 truncate-text" style={{ color: "#aab4bd" }}>
                  {post.post_copy}
                </p>

                <p className="text-[10.5px] font-mono mb-2" style={{ color: "#5b6673" }}>
                  {formatScheduledFor(post.scheduled_for)} · {imageStatusLabel(post)}
                </p>

                {post.status !== "published" && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      onClick={() => review(post.id, "approved")}
                      disabled={post.status === "approved"}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                      style={{ border: "1px solid #5eead4", color: post.status === "approved" ? "#3a4250" : "#5eead4", backgroundColor: "transparent" }}
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => review(post.id, "rejected")}
                      disabled={post.status === "rejected"}
                      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
                      style={{ border: "1px solid #3a4250", color: post.status === "rejected" ? "#3a4250" : "#8b96a3", backgroundColor: "transparent" }}
                    >
                      Reject
                    </button>
                    <input
                      type="datetime-local"
                      defaultValue={post.scheduled_for ? post.scheduled_for.slice(0, 16) : ""}
                      onBlur={(e) => reschedule(post.id, e.target.value)}
                      className="text-[10.5px] font-mono px-2 py-1 rounded-[6px]"
                      style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#aab4bd" }}
                      title="Reschedule this post"
                    />
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
