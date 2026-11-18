'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// G2 + G3 (item 5): a fixed problem that came back says so, and links the
// incident that claimed to fix it; an alert source's own "resolved" is shown
// as what it is: the source's report, not a verified fix.

import type { Incident } from '@/lib/types'
import { timeAgo } from '@/lib/utils'

export function RegressionBadge({ incident }: { incident: Incident }) {
  if (!incident.is_regression) return null
  return (
    <span
      className="shrink-0 rounded border border-red-500/40 bg-red-500/10 px-1.5 py-0.5 text-xs font-medium text-red-300"
      title={`Came back after incident ${incident.previous_incident_id} was fixed`}
    >
      Regression
    </span>
  )
}

export function IncidentHistoryNote({ incident }: { incident: Incident }) {
  const prev = incident.previous_incident_id
  if (!prev && !incident.source_resolved_at) return null
  return (
    <div className="mb-2 space-y-1 text-xs">
      {prev && (
        <p className={incident.is_regression ? 'text-red-300' : 'text-zinc-400'}>
          {incident.is_regression ? 'This came back after ' : 'Seen before: '}
          <span className="font-mono">#{prev.slice(0, 8)}</span>
          {incident.is_regression ? ' was fixed.' : ' (not fixed at the time).'}
        </p>
      )}
      {incident.source_resolved_at && (
        <p className="text-zinc-400">
          The alert source reported this resolved {timeAgo(incident.source_resolved_at)}.
          {' '}Cloud Decoded re-checks the live resource before calling it fixed.
        </p>
      )}
    </div>
  )
}
