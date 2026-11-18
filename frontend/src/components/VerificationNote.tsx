'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// The last post-fix live re-check (G4, migration 064), shown on the card so
// "verified" / "didn't work" always comes with what was actually read.

import type { Incident } from '@/lib/types'
import { timeAgo } from '@/lib/utils'

const OUTCOME_LABEL: Record<string, string> = {
  fixed: 'Fixed',
  not_fixed: 'Not fixed yet',
  unknown: "Couldn't check",
  unverifiable: 'Not verified',
}

export function VerificationNote({ result }: { result: Incident['verification_result'] }) {
  if (!result) return null
  return (
    <p className="mt-2 rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-left font-mono text-[11px] leading-relaxed text-zinc-400">
      <span className="text-zinc-300">{OUTCOME_LABEL[result.outcome] ?? result.outcome}</span>
      {' · '}check {result.attempt} · {timeAgo(result.checked_at)}
      <br />
      {result.detail}
    </p>
  )
}
