"use client";

import { useEffect, useState } from "react";
import { fetchPendingCount } from "@/lib/email-campaigns-api";

// Polling badge for the Email Campaigns sidebar item -- lightweight
// indicator only, matches the visual weight of other status pills in
// this app rather than a new notification infrastructure layer.
export function EmailCampaignsNavBadge() {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await fetchPendingCount();
        if (!cancelled) setCount(data.total);
      } catch {
        // Silent -- a failed poll just leaves the badge as it was, the
        // queue page itself surfaces per-feed errors in detail.
      }
    }
    poll();
    const timer = setInterval(poll, 60000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (!count) return null;

  return (
    <span
      className="ml-auto text-[9.5px] font-mono font-semibold px-1.5 rounded-full shrink-0"
      style={{ backgroundColor: "#e8963f22", color: "#e8963f", minWidth: 16, textAlign: "center" }}
    >
      {count}
    </span>
  );
}
