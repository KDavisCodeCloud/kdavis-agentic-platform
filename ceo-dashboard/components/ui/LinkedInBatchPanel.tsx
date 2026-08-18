"use client";

import { useState } from "react";
import { FireLinkedInPosts } from "./FireLinkedInPosts";
import { LinkedInBatchReview } from "./LinkedInBatchReview";

// Thin client wrapper holding the refreshSignal state shared between the
// fire button and the review panel below it — MarketingPage itself is a
// server component, so this state can't live there.
export function LinkedInBatchPanel() {
  const [refreshSignal, setRefreshSignal] = useState<{ batchMonth: string; nonce: number } | undefined>();

  return (
    <div>
      <FireLinkedInPosts
        onFired={(batchMonth) => setRefreshSignal({ batchMonth, nonce: Date.now() })}
      />
      <div className="my-4" style={{ borderTop: "1px solid #1c222b" }} />
      <LinkedInBatchReview refreshSignal={refreshSignal} />
    </div>
  );
}
