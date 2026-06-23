import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export function fmtDuration(seconds: number | null): string {
  if (!seconds) return '—'
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

export function agentLabel(agentId: string): string {
  const map: Record<string, string> = {
    agent_01_cicd_triage:     'CI/CD Triage',
    agent_02_k8s_alert:       'K8s Alerts',
    agent_03_pr_review:       'PR Review',
    agent_04_migration:       'Migration',
    agent_05_iam_minimizer:   'IAM Policy',
    agent_06_finops:          'FinOps',
    agent_07_runbook:         'Runbook',
    agent_08_drift_detection: 'Drift',
    agent_09_onboarding_buddy:'Onboarding',
    agent_10_dependency_patch:'Dep Patch',
  }
  return map[agentId] ?? agentId
}
