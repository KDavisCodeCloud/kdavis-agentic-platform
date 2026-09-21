// Client-side fetch wrappers for the Email Campaign HITL queue
// (app/dashboard/email-campaigns). These call THIS app's own proxy routes
// under app/api/email-campaigns/**, never the backends directly -- see
// lib/email-campaigns/{cloud-decoded,mse}-client.ts for where the real
// backend calls and auth happen, server-side only.
import { assertNotRedirectedToLogin } from "./api";
import type { EmailCampaignTemplate, EmailCampaignTemplateDetail, EmailCampaignMetrics, MseCampaignStatus, EmailFeedSource } from "./types";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, cache: "no-store" });
  assertNotRedirectedToLogin(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Request to ${url} failed: ${res.status}`);
  }
  return res.json();
}

function feedBase(source: EmailFeedSource): string {
  return source === "cloud-decoded" ? "/api/email-campaigns/cloud-decoded" : "/api/email-campaigns/mse";
}

export async function fetchTemplates(source: EmailFeedSource, statusFilter?: string): Promise<EmailCampaignTemplate[]> {
  const param = source === "cloud-decoded" ? "status_filter" : "status";
  const qs = statusFilter ? `?${param}=${encodeURIComponent(statusFilter)}` : "";
  const data = await req<EmailCampaignTemplate[]>(`${feedBase(source)}/templates${qs}`);
  return data;
}

export async function fetchTemplateDetail(source: EmailFeedSource, key: string): Promise<EmailCampaignTemplateDetail> {
  return req(`${feedBase(source)}/templates/${encodeURIComponent(key)}`);
}

export async function updateTemplate(
  key: string,
  body: { subject?: string; preheader?: string; body_html?: string; body_text?: string; cta_url?: string }
): Promise<EmailCampaignTemplate> {
  // Edit-in-place only exists on the Cloud Decoded feed's contract.
  return req(`/api/email-campaigns/cloud-decoded/templates/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function approveTemplate(source: EmailFeedSource, key: string): Promise<void> {
  await req(`${feedBase(source)}/templates/${encodeURIComponent(key)}/approve`, { method: "POST" });
}

export async function retireTemplate(source: EmailFeedSource, key: string): Promise<void> {
  await req(`${feedBase(source)}/templates/${encodeURIComponent(key)}/retire`, { method: "POST" });
}

export async function activateSequence(sequenceKey: string): Promise<void> {
  // Sequence activation is a Cloud Decoded-only concept -- MSE's
  // mse_email_sequences rows ARE the whole sequence; "approve" is its
  // terminal action, there's nothing further to "activate".
  await req(`/api/email-campaigns/cloud-decoded/sequences/${encodeURIComponent(sequenceKey)}/activate`, { method: "POST" });
}

export async function deactivateSequence(sequenceKey: string): Promise<void> {
  await req(`/api/email-campaigns/cloud-decoded/sequences/${encodeURIComponent(sequenceKey)}/deactivate`, { method: "POST" });
}

export async function fetchMetrics(source: EmailFeedSource): Promise<EmailCampaignMetrics[]> {
  return req(`${feedBase(source)}/metrics`);
}

export async function fetchMseCampaignStatus(): Promise<MseCampaignStatus> {
  return req(`/api/email-campaigns/mse/campaign-status`);
}

export interface PendingCount {
  total: number;
  cloudDecoded: number;
  mse: number;
}

export async function fetchPendingCount(): Promise<PendingCount> {
  return req(`/api/email-campaigns/pending-count`);
}
