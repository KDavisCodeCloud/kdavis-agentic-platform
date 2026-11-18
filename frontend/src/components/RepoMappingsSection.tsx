'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// Settings → Repositories (G13, migration 063). Where this workspace's
// Terraform lives, so Agents 08 and 11 can propose a one-block PR for a
// resource whose alert names no repo (SNS / Azure Monitor never do).
// Admin-only; rendered inside PoliciesPanel's admin view with its own
// load/save so it works independently of the policy endpoints.

import { useCallback, useEffect, useState } from 'react'
import { GitBranch, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { listRepoMappings, saveRepoMappings } from '@/lib/api'
import type { RepoMapping } from '@/lib/types'

const EMPTY_RULE: RepoMapping = { match_prefix: '', repository: '', base_branch: 'main', iac_path: '' }
const INPUT =
  'w-full min-w-0 rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 font-mono text-xs text-zinc-200 ' +
  'placeholder:text-zinc-600 focus:border-blue-500/50 focus:outline-none'

export function RepoMappingsSection({ token }: { token: string }) {
  const [defaultRule, setDefaultRule] = useState<RepoMapping | null>(null)
  const [rules, setRules] = useState<RepoMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const all = await listRepoMappings(token)
      setDefaultRule(all.find(m => !m.match_prefix) ?? null)
      setRules(all.filter(m => m.match_prefix))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load repository mappings')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  function updateRule(index: number, patch: Partial<RepoMapping>) {
    setSaved(false)
    setRules(prev => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }

  async function handleSave() {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const mappings = [
        ...(defaultRule && defaultRule.repository.trim() ? [{ ...defaultRule, match_prefix: null }] : []),
        ...rules,
      ]
      const result = await saveRepoMappings(token, mappings)
      setDefaultRule(result.find(m => !m.match_prefix) ?? null)
      setRules(result.filter(m => m.match_prefix))
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save repository mappings')
    } finally {
      setSaving(false)
    }
  }

  const dflt = defaultRule ?? { ...EMPTY_RULE, match_prefix: null }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
      <div className="mb-3 flex items-center gap-2">
        <GitBranch className="h-4 w-4 text-zinc-400" />
        <h3 className="text-sm font-semibold text-zinc-100">Repositories</h3>
      </div>
      <p className="mb-4 text-xs leading-relaxed text-zinc-500">
        Where your Terraform lives. Cloud alerts don&apos;t say which repo a resource is defined in, so without a
        mapping Drift Detection and Resource Health can only open an issue. With one, they propose a PR that
        changes just that resource&apos;s block — you see the exact diff before approving, and terraform fmt and
        validate must pass before the PR is opened. The longest matching prefix wins; otherwise the default.
      </p>

      {loading ? (
        <p className="text-xs text-zinc-600">Loading…</p>
      ) : (
        <div className="space-y-3">
          <fieldset className="rounded border border-zinc-800 bg-zinc-950/60 p-3">
            <legend className="px-1 text-[11px] font-medium text-zinc-400">Default (every other resource)</legend>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,2fr)]">
              <input className={INPUT} aria-label="Default repository" placeholder="owner/repo"
                value={dflt.repository}
                onChange={e => { setSaved(false); setDefaultRule({ ...dflt, repository: e.target.value }) }} />
              <input className={INPUT} aria-label="Default branch" placeholder="main"
                value={dflt.base_branch}
                onChange={e => { setSaved(false); setDefaultRule({ ...dflt, base_branch: e.target.value }) }} />
              <input className={INPUT} aria-label="Default .tf file" placeholder="infra/main.tf"
                value={dflt.iac_path}
                onChange={e => { setSaved(false); setDefaultRule({ ...dflt, iac_path: e.target.value }) }} />
            </div>
          </fieldset>

          {rules.map((rule, i) => (
            <div key={i} className="rounded border border-zinc-800 bg-zinc-950/60 p-3">
              <div className="mb-2 flex items-center gap-2">
                <input className={INPUT} aria-label={`Rule ${i + 1} resource ID prefix`}
                  placeholder="Resource ID prefix, e.g. /subscriptions/…/resourceGroups/rg-prod"
                  value={rule.match_prefix ?? ''} onChange={e => updateRule(i, { match_prefix: e.target.value })} />
                <Button size="sm" variant="ghost" className="h-8 w-8 shrink-0 p-0" aria-label={`Remove rule ${i + 1}`}
                  onClick={() => { setSaved(false); setRules(prev => prev.filter((_, j) => j !== i)) }}>
                  <Trash2 className="h-3.5 w-3.5 text-zinc-500" />
                </Button>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,2fr)]">
                <input className={INPUT} aria-label={`Rule ${i + 1} repository`} placeholder="owner/repo"
                  value={rule.repository} onChange={e => updateRule(i, { repository: e.target.value })} />
                <input className={INPUT} aria-label={`Rule ${i + 1} branch`} placeholder="main"
                  value={rule.base_branch} onChange={e => updateRule(i, { base_branch: e.target.value })} />
                <input className={INPUT} aria-label={`Rule ${i + 1} .tf file`} placeholder="azure/main.tf"
                  value={rule.iac_path} onChange={e => updateRule(i, { iac_path: e.target.value })} />
              </div>
            </div>
          ))}

          {error && (
            <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="ghost" className="border border-zinc-700"
              onClick={() => { setSaved(false); setRules(prev => [...prev, { ...EMPTY_RULE }]) }}>
              <Plus className="h-3.5 w-3.5" />
              Add a prefix rule
            </Button>
            <Button size="sm" disabled={saving} loading={saving} onClick={handleSave}>Save repositories</Button>
            {saved && <span className="text-xs text-emerald-400">Saved</span>}
          </div>
        </div>
      )}
    </div>
  )
}
