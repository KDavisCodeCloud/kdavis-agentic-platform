// Cloud Decoded — typed API client

import type { Incident, ApprovalRequest, ApprovalResponse, AgentsResponse } from './types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Workspace-Token': token,
      ...options.headers,
    },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`)
  }

  return res.json() as Promise<T>
}

// ── Incidents ──────────────────────────────────────────────────────────

export async function listIncidents(
  token: string,
  statusFilter?: string,
): Promise<Incident[]> {
  const qs = statusFilter ? `?status_filter=${statusFilter}` : ''
  return request<Incident[]>(`/incidents${qs}`, token)
}

export async function getIncident(token: string, incidentId: string): Promise<Incident> {
  return request<Incident>(`/incidents/${incidentId}`, token)
}

export async function approveIncident(
  token: string,
  incidentId: string,
  body: ApprovalRequest,
): Promise<ApprovalResponse> {
  return request<ApprovalResponse>(`/incidents/${incidentId}/approve`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ── Agents ─────────────────────────────────────────────────────────────

export async function listAgents(token: string): Promise<AgentsResponse> {
  return request<AgentsResponse>('/agents', token)
}

// ── Health ─────────────────────────────────────────────────────────────

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`)
    return res.ok
  } catch {
    return false
  }
}
