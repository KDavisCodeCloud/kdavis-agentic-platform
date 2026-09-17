'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// 24-gap-closure Phase 4 -- Members & Security. GET /workspace-members
// already existed (Phase 2's assignment picker was, until now, the only
// caller) but had no standalone management UI: no way to invite, view
// the full roster, or remove someone short of a raw API call. This panel
// is that UI, plus the two other Phase 4 member-security features that
// naturally live next to it: personal TOTP enrollment and (Enterprise,
// admin-only) requiring MFA workspace-wide.

import { useCallback, useEffect, useState } from 'react'
import { Users, UserPlus, UserMinus, ShieldCheck, ShieldOff, Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  listWorkspaceMembers, inviteWorkspaceMember, deactivateWorkspaceMember,
  getConnectionsStatus, setRequireMfa, isMemberSessionToken,
} from '@/lib/api'
import type { WorkspaceMember, ConnectionsStatus } from '@/lib/types'
import { getSupabaseClient, isSupabaseConfigured } from '@/lib/supabase'

interface MembersPanelProps {
  token: string
}

const ROLE_OPTIONS = ['viewer', 'approver', 'admin'] as const

const STATUS_STYLES: Record<string, string> = {
  active: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  invited: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
  deactivated: 'text-zinc-500 bg-zinc-500/10 border-zinc-600/30',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10.5px] font-mono uppercase ${STATUS_STYLES[status] ?? STATUS_STYLES.deactivated}`}>
      {status}
    </span>
  )
}

export function MembersPanel({ token }: MembersPanelProps) {
  const [members, setMembers] = useState<WorkspaceMember[]>([])
  const [seatsUsed, setSeatsUsed] = useState(0)
  const [maxSeats, setMaxSeats] = useState(-1)
  const [connections, setConnections] = useState<ConnectionsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<string>('viewer')
  const [inviting, setInviting] = useState(false)
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null)

  const [mfaEnrolled, setMfaEnrolled] = useState(false)
  const [mfaFactorId, setMfaFactorId] = useState<string | null>(null)
  const [mfaEnrollQr, setMfaEnrollQr] = useState<string | null>(null)
  const [mfaEnrollSecret, setMfaEnrollSecret] = useState<string | null>(null)
  const [mfaEnrollCode, setMfaEnrollCode] = useState('')
  const [mfaBusy, setMfaBusy] = useState(false)
  const [mfaError, setMfaError] = useState('')
  const [secretCopied, setSecretCopied] = useState(false)
  const [requireMfaBusy, setRequireMfaBusy] = useState(false)

  const isAdmin = connections?.member_role === null || connections?.member_role === 'admin'
  const isEnterprise = connections?.product_tier === 'enterprise'

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [membersResult, connResult] = await Promise.all([
        listWorkspaceMembers(token),
        getConnectionsStatus(token),
      ])
      setMembers(membersResult.members)
      setSeatsUsed(membersResult.seats_used)
      setMaxSeats(membersResult.max_seats)
      setConnections(connResult)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load members')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!isSupabaseConfigured() || isMemberSessionToken(token) === false) return
    getSupabaseClient().auth.mfa.listFactors().then(({ data }) => {
      const factor = data?.totp?.find(f => f.status === 'verified')
      setMfaEnrolled(!!factor)
      setMfaFactorId(factor?.id ?? null)
    }).catch(() => {})
  }, [token])

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!inviteEmail.trim()) return
    setInviting(true)
    try {
      await inviteWorkspaceMember(token, inviteEmail.trim(), inviteRole)
      setInviteEmail('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to invite member')
    } finally {
      setInviting(false)
    }
  }

  async function handleDeactivate(memberId: string) {
    setError('')
    setDeactivatingId(memberId)
    try {
      await deactivateWorkspaceMember(token, memberId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove member')
    } finally {
      setDeactivatingId(null)
    }
  }

  async function handleStartEnroll() {
    setMfaError('')
    setMfaBusy(true)
    try {
      const supabase = getSupabaseClient()
      const { data, error: enrollError } = await supabase.auth.mfa.enroll({ factorType: 'totp' })
      if (enrollError || !data) {
        setMfaError(enrollError?.message || 'Could not start enrollment')
        return
      }
      setMfaFactorId(data.id)
      setMfaEnrollQr(data.totp.qr_code)
      setMfaEnrollSecret(data.totp.secret)
    } catch (err) {
      setMfaError(err instanceof Error ? err.message : 'Could not start enrollment')
    } finally {
      setMfaBusy(false)
    }
  }

  async function handleConfirmEnroll(e: React.FormEvent) {
    e.preventDefault()
    setMfaError('')
    if (!mfaFactorId || mfaEnrollCode.trim().length !== 6) {
      setMfaError('Enter the 6-digit code from your authenticator app')
      return
    }
    setMfaBusy(true)
    try {
      const supabase = getSupabaseClient()
      const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({ factorId: mfaFactorId })
      if (challengeError || !challenge) {
        setMfaError(challengeError?.message || 'Could not verify code')
        return
      }
      const { error: verifyError } = await supabase.auth.mfa.verify({
        factorId: mfaFactorId, challengeId: challenge.id, code: mfaEnrollCode.trim(),
      })
      if (verifyError) {
        setMfaError(verifyError.message)
        return
      }
      setMfaEnrolled(true)
      setMfaEnrollQr(null)
      setMfaEnrollSecret(null)
      setMfaEnrollCode('')
    } catch (err) {
      setMfaError(err instanceof Error ? err.message : 'Could not verify code')
    } finally {
      setMfaBusy(false)
    }
  }

  async function handleUnenroll() {
    if (!mfaFactorId) return
    setMfaBusy(true)
    setMfaError('')
    try {
      const supabase = getSupabaseClient()
      const { error: unenrollError } = await supabase.auth.mfa.unenroll({ factorId: mfaFactorId })
      if (unenrollError) {
        setMfaError(unenrollError.message)
        return
      }
      setMfaEnrolled(false)
      setMfaFactorId(null)
    } catch (err) {
      setMfaError(err instanceof Error ? err.message : 'Could not disable two-factor authentication')
    } finally {
      setMfaBusy(false)
    }
  }

  async function handleToggleRequireMfa() {
    if (!connections) return
    setRequireMfaBusy(true)
    setError('')
    try {
      const next = !connections.require_mfa
      await setRequireMfa(token, next)
      setConnections({ ...connections, require_mfa: next })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update the workspace MFA requirement')
    } finally {
      setRequireMfaBusy(false)
    }
  }

  if (loading) return <p className="text-xs text-zinc-600">Loading members…</p>

  return (
    <div className="space-y-6 p-6">
      {error && (
        <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
      )}

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-zinc-400" />
            <h3 className="text-sm font-semibold text-zinc-100">Members</h3>
          </div>
          <span className="font-mono text-[11px] text-zinc-500">
            {seatsUsed} / {maxSeats === -1 ? 'unlimited' : maxSeats} seats
          </span>
        </div>

        <div className="space-y-1.5">
          {members.map(m => (
            <div key={m.id} className="flex items-center justify-between gap-2 rounded border border-zinc-800/70 bg-zinc-950/40 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-xs text-zinc-200">{m.email}</span>
                <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10.5px] font-mono text-zinc-400">{m.role}</span>
                <StatusBadge status={m.status} />
              </div>
              {isAdmin && m.status !== 'deactivated' && (
                <Button
                  size="sm" variant="ghost"
                  disabled={deactivatingId === m.id}
                  loading={deactivatingId === m.id}
                  onClick={() => handleDeactivate(m.id)}
                  title="Remove this member"
                >
                  <UserMinus className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ))}
          {members.length === 0 && <p className="text-xs text-zinc-600">No members yet.</p>}
        </div>

        {isAdmin && (
          <form onSubmit={handleInvite} className="mt-4 flex items-end gap-2 border-t border-zinc-800 pt-4">
            <div className="flex-1">
              <label className="mb-1 block text-[11px] text-zinc-500">Invite by email</label>
              <input
                type="email"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                placeholder="teammate@company.com"
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-zinc-500">Role</label>
              <select
                value={inviteRole}
                onChange={e => setInviteRole(e.target.value)}
                className="rounded border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 outline-none focus:border-blue-500"
              >
                {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <Button type="submit" size="sm" disabled={inviting || !inviteEmail.trim()} loading={inviting}>
              <UserPlus className="h-3.5 w-3.5" /> Invite
            </Button>
          </form>
        )}
      </div>

      {isMemberSessionToken(token) && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
          <div className="mb-3 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-zinc-400" />
            <h3 className="text-sm font-semibold text-zinc-100">Two-factor authentication</h3>
          </div>
          <p className="mb-4 text-xs text-zinc-500">Require a code from an authenticator app in addition to your password.</p>

          {mfaError && <p className="mb-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{mfaError}</p>}

          {mfaEnrolled ? (
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs text-emerald-400"><Check className="h-3.5 w-3.5" /> Enabled</span>
              <Button size="sm" variant="outline" disabled={mfaBusy} loading={mfaBusy} onClick={handleUnenroll}>
                <ShieldOff className="h-3.5 w-3.5" /> Disable
              </Button>
            </div>
          ) : mfaEnrollQr ? (
            <form onSubmit={handleConfirmEnroll} className="space-y-3">
              <p className="text-xs text-zinc-400">Scan this QR code with your authenticator app, then enter the 6-digit code it shows.</p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={mfaEnrollQr} alt="TOTP enrollment QR code" className="h-40 w-40 rounded bg-white p-2" />
              {mfaEnrollSecret && (
                <div className="flex items-center gap-2">
                  <code className="rounded bg-zinc-950 px-2 py-1 text-[11px] text-zinc-400">{mfaEnrollSecret}</code>
                  <Button
                    type="button" size="sm" variant="ghost"
                    onClick={() => {
                      navigator.clipboard.writeText(mfaEnrollSecret)
                      setSecretCopied(true)
                      setTimeout(() => setSecretCopied(false), 1500)
                    }}
                  >
                    {secretCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              )}
              <input
                type="text" inputMode="numeric" maxLength={6}
                value={mfaEnrollCode}
                onChange={e => setMfaEnrollCode(e.target.value.replace(/\D/g, ''))}
                placeholder="123456"
                className="w-32 rounded border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-center font-mono text-sm text-zinc-100 outline-none focus:border-blue-500"
              />
              <Button type="submit" size="sm" disabled={mfaBusy} loading={mfaBusy}>Confirm</Button>
            </form>
          ) : (
            <Button size="sm" disabled={mfaBusy} loading={mfaBusy} onClick={handleStartEnroll}>
              <ShieldCheck className="h-3.5 w-3.5" /> Enable two-factor authentication
            </Button>
          )}
        </div>
      )}

      {isAdmin && isEnterprise && connections && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
          <div className="mb-3 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-zinc-400" />
            <h3 className="text-sm font-semibold text-zinc-100">Require MFA workspace-wide</h3>
          </div>
          <p className="mb-4 text-xs text-zinc-500">
            Enterprise setting. When on, every member must complete two-factor authentication to sign in --
            a member session without a verified factor is rejected until they enroll.
          </p>
          <Button
            size="sm"
            variant={connections.require_mfa ? 'warning' : 'outline'}
            disabled={requireMfaBusy}
            loading={requireMfaBusy}
            onClick={handleToggleRequireMfa}
          >
            {connections.require_mfa ? 'Turn off' : 'Turn on'}
          </Button>
        </div>
      )}
    </div>
  )
}
