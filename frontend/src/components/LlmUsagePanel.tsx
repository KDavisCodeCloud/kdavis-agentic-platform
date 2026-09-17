'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// 24-gap-closure Phase 7 -- LLM usage visibility. token_usage
// (db/schema.sql) was already written to on every real agent LLM call
// via core/token_budget.py's record_usage -- there was simply no
// dashboard read of it anywhere before this panel.

import { useEffect, useState } from 'react'
import { DollarSign } from 'lucide-react'
import { getLlmUsage } from '@/lib/api'
import { agentLabel } from '@/lib/utils'
import type { LlmUsage } from '@/lib/types'

interface LlmUsagePanelProps {
  token: string
}

export function LlmUsagePanel({ token }: LlmUsagePanelProps) {
  const [usage, setUsage] = useState<LlmUsage | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getLlmUsage(token).then(setUsage).catch(err => setError(err instanceof Error ? err.message : 'Failed to load usage'))
  }, [token])

  if (error) return <p className="p-6 text-xs text-red-400">{error}</p>
  if (!usage) return <p className="p-6 text-xs text-zinc-600">Loading usage…</p>

  const maxAgentCost = Math.max(...usage.by_agent.map(a => a.cost_usd), 0.01)

  return (
    <div className="space-y-6 p-6">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
        <div className="mb-4 flex items-center gap-2">
          <DollarSign className="h-4 w-4 text-zinc-400" />
          <h3 className="text-sm font-semibold text-zinc-100">
            LLM usage — {usage.billing_month}
          </h3>
        </div>

        <div className="mb-5 grid grid-cols-3 gap-4">
          <div>
            <p className="font-mono text-2xl font-bold text-zinc-100">
              ${usage.total_cost_usd.toFixed(2)}
            </p>
            <p className="text-[11px] text-zinc-500">Spent this month</p>
          </div>
          <div>
            <p className="font-mono text-2xl font-bold text-zinc-100">
              {usage.total_tokens.toLocaleString()}
            </p>
            <p className="text-[11px] text-zinc-500">Tokens used</p>
          </div>
          <div>
            <p className={`font-mono text-2xl font-bold ${usage.utilization_pct >= 90 ? 'text-red-400' : usage.utilization_pct >= 70 ? 'text-amber-400' : 'text-emerald-400'}`}>
              {usage.utilization_pct}%
            </p>
            <p className="text-[11px] text-zinc-500">
              of ${usage.budget_usd.toFixed(0)} budget
            </p>
          </div>
        </div>

        <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-zinc-500">By agent</h4>
        <div className="space-y-2">
          {usage.by_agent.length === 0 && (
            <p className="text-xs text-zinc-600">No LLM usage recorded yet this month.</p>
          )}
          {usage.by_agent.map(agent => (
            <div key={agent.agent_id} className="flex items-center gap-3">
              <span className="w-32 shrink-0 truncate text-xs text-zinc-300">{agentLabel(agent.agent_id)}</span>
              <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                <div
                  className="h-full rounded bg-blue-500/70"
                  style={{ width: `${(agent.cost_usd / maxAgentCost) * 100}%` }}
                />
              </div>
              <span className="w-20 shrink-0 text-right font-mono text-xs text-zinc-400">
                ${agent.cost_usd.toFixed(2)}
              </span>
              <span className="w-24 shrink-0 text-right font-mono text-[11px] text-zinc-600">
                {agent.tokens_used.toLocaleString()} tok
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
