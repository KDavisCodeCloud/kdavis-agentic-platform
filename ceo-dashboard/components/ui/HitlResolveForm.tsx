"use client";

import { useState, useTransition } from "react";
import { resolveHitlTicket } from "@/app/dashboard/empire/actions";

export function HitlResolveForm({ ticketId }: { ticketId: string }) {
  const [resolution, setResolution] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(null);
    startTransition(async () => {
      const result = await resolveHitlTicket(ticketId, resolution);
      if (!result.ok) setError(result.error ?? "Failed to resolve.");
    });
  }

  return (
    <div className="flex items-center gap-2 mt-2">
      <input
        type="text"
        value={resolution}
        onChange={(e) => setResolution(e.target.value)}
        placeholder="Resolution / decision..."
        disabled={pending}
        className="flex-1 text-[11px] font-mono px-2.5 py-1.5 rounded-[6px]"
        style={{ backgroundColor: "#10151b", border: "1px solid #1c222b", color: "#eef2f5" }}
      />
      <button
        onClick={submit}
        disabled={pending || !resolution.trim()}
        className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold shrink-0"
        style={{
          border: "1px solid #5eead4",
          color: "#5eead4",
          backgroundColor: "transparent",
          opacity: pending || !resolution.trim() ? 0.5 : 1,
        }}
      >
        {pending ? "Resolving…" : "Resolve"}
      </button>
      {error && (
        <span className="text-[10px] font-mono shrink-0" style={{ color: "#e05d5d" }}>
          {error}
        </span>
      )}
    </div>
  );
}
