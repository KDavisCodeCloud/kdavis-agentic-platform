"use client";

import { useState } from "react";
import { generateLinkedInPosts } from "@/lib/api";

const PILLAR_OPTIONS: { value: string | null; label: string }[] = [
  { value: null, label: "Balanced mix (40/30/20/10)" },
  { value: "pillar_1", label: "Cloud & AI Execution" },
  { value: "pillar_2", label: "Builder's Journey" },
  { value: "pillar_3", label: "Philosophy, Faith & Gardening" },
  { value: "pillar_4", label: "Product, Business & CTA" },
];

interface Props {
  // Bumped after a successful fire so the sibling LinkedInBatchReview panel
  // re-fetches and jumps to whichever batch_month the new posts landed in.
  onFired?: (batchMonth: string) => void;
}

export function FireLinkedInPosts({ onFired }: Props) {
  const [count, setCount] = useState(5);
  const [pillarFocus, setPillarFocus] = useState<string | null>(null);
  const [firing, setFiring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  async function fire() {
    setFiring(true);
    setError(null);
    setResult(null);
    try {
      const { post_count, posts } = await generateLinkedInPosts(count, pillarFocus);
      const byPillar = new Map<string, number>();
      for (const p of posts) byPillar.set(p.pillar_name, (byPillar.get(p.pillar_name) ?? 0) + 1);
      const breakdown = Array.from(byPillar.entries()).map(([name, n]) => `${n} ${name}`).join(", ");
      setResult(`${post_count} post${post_count === 1 ? "" : "s"} drafted and queued for review${breakdown ? ` — ${breakdown}` : ""}.`);
      const firstBatchMonth = posts[0]?.scheduled_for?.slice(0, 7);
      if (firstBatchMonth) onFired?.(firstBatchMonth);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Firing posts failed");
    } finally {
      setFiring(false);
    }
  }

  return (
    <div>
      <p className="text-[11px] font-mono mb-3" style={{ color: "#5b6673" }}>
        Draft posts on demand, outside the monthly batch — same MKT-LI1 voice and pillar mix, no research/idea
        input needed. Drafts land in the review queue below; nothing publishes without approval.
      </p>
      <div className="flex items-center gap-2 flex-wrap">
        <label className="flex items-center gap-1.5 text-[11px] font-mono" style={{ color: "#8b96a3" }}>
          Posts
          <input
            type="number"
            min={1}
            max={30}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(30, Number(e.target.value) || 1)))}
            className="font-mono px-2 py-1 rounded-[6px] w-16"
            style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", minHeight: 44, fontSize: 16 }}
          />
        </label>

        <select
          value={pillarFocus ?? ""}
          onChange={(e) => setPillarFocus(e.target.value || null)}
          className="font-mono px-2 py-1 rounded-[6px]"
          style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5", minHeight: 44, fontSize: 16 }}
        >
          {PILLAR_OPTIONS.map((opt) => (
            <option key={opt.label} value={opt.value ?? ""}>
              {opt.label}
            </option>
          ))}
        </select>

        <button
          onClick={fire}
          disabled={firing}
          className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors shrink-0"
          style={{
            border: "1px solid #f5a623",
            color: "#f5a623",
            backgroundColor: "transparent",
            opacity: firing ? 0.6 : 1,
            minHeight: 44,
          }}
          title="Drafts the posts now and queues them for review — never publishes directly."
        >
          {firing ? "Firing…" : `🔥 Fire ${count} post${count === 1 ? "" : "s"}`}
        </button>
      </div>

      {error && (
        <p className="text-[11px] font-mono mt-2" style={{ color: "#e05d5d" }}>{error}</p>
      )}
      {result && (
        <p className="text-[11px] font-mono mt-2" style={{ color: "#6fce8f" }}>{result}</p>
      )}
    </div>
  );
}
