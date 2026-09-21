import type { EmailCampaignTemplate, EmailCampaignTemplateDetail, EmailCampaignMetrics } from "@/lib/types";
import { backendFetch, type BackendResult } from "./http";

// Cloud Decoded's own backend (api/routes/... in kdavis-agentic-platform),
// contract documented in docs/internal/email-approval-api.md (repo root).
// Auth is the signed-in admin's OWN Supabase session JWT, forwarded
// as-is -- ceo-dashboard and Cloud Decoded share the same Supabase
// project (see that doc's "Auth" section), so there is no separate
// static API key for this feed, unlike the MSE feed.
const BASE_PATH = "/api/v1/internal/email";

export function isCloudDecodedEnabled(): boolean {
  return process.env.EMAIL_CAMPAIGNS_CD_ENABLED !== "false";
}

function baseUrl(): string | null {
  return process.env.NEXT_PUBLIC_API_URL || null;
}

interface RawCdTemplate {
  template_key: string;
  sequence_key: string;
  step_number: number | null;
  subject: string | null;
  preheader: string | null;
  status: string;
  origin: "generated" | "adapted_from_script";
  source_script: string | null;
  cta_url: string | null;
  skip_if: string | null;
  approved_at: string | null;
  approved_by: string | null;
  product: string;
}

function normalizeTemplate(raw: RawCdTemplate): EmailCampaignTemplate {
  return {
    source: "cloud-decoded",
    templateKey: raw.template_key,
    sequenceKey: raw.sequence_key,
    stepNumber: raw.step_number,
    subject: raw.subject,
    preheader: raw.preheader,
    status: raw.status as EmailCampaignTemplate["status"],
    origin: raw.origin,
    sourceScript: raw.source_script,
    ctaUrl: raw.cta_url,
    skipIf: raw.skip_if,
    approvedAt: raw.approved_at,
    approvedBy: raw.approved_by,
    productLabel: raw.product || "cloud-decoded",
    productResolved: true,
    createdAt: null,
  };
}

function normalizeMetrics(raw: {
  sequence_key: string;
  sends: number; clicks: number; unsubscribes: number;
  conversions: number; revenue_usd_estimate: number;
}): EmailCampaignMetrics {
  return {
    source: "cloud-decoded",
    sequenceKey: raw.sequence_key,
    sends: raw.sends,
    clicks: raw.clicks,
    unsubscribes: raw.unsubscribes,
    conversions: raw.conversions,
    revenueUsd: raw.revenue_usd_estimate,
    note: null,
  };
}

function guard(): { ok: false; status: number; error: string } | null {
  if (!isCloudDecodedEnabled()) {
    return { ok: false, status: 503, error: "Cloud Decoded email feed is disabled (EMAIL_CAMPAIGNS_CD_ENABLED=false)" };
  }
  if (!baseUrl()) {
    return { ok: false, status: 500, error: "NEXT_PUBLIC_API_URL is not configured on this deployment" };
  }
  return null;
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

export async function listCdTemplates(
  token: string,
  opts: { statusFilter?: string; sequenceKey?: string } = {}
): Promise<BackendResult<EmailCampaignTemplate[]>> {
  const blocked = guard();
  if (blocked) return blocked;

  const url = new URL(`${baseUrl()}${BASE_PATH}/templates`);
  if (opts.statusFilter) url.searchParams.set("status_filter", opts.statusFilter);
  if (opts.sequenceKey) url.searchParams.set("sequence_key", opts.sequenceKey);

  const result = await backendFetch<RawCdTemplate[]>(url.toString(), { headers: authHeaders(token) }, "Cloud Decoded");
  if (!result.ok) return result;
  return { ok: true, data: result.data.map(normalizeTemplate) };
}

export async function getCdTemplate(token: string, key: string): Promise<BackendResult<EmailCampaignTemplateDetail>> {
  const blocked = guard();
  if (blocked) return blocked;

  const result = await backendFetch<RawCdTemplate & {
    body_html: string; body_text: string; rendered_html: string; rendered_text: string;
  }>(`${baseUrl()}${BASE_PATH}/templates/${encodeURIComponent(key)}`, { headers: authHeaders(token) }, "Cloud Decoded");
  if (!result.ok) return result;
  return {
    ok: true,
    data: {
      ...normalizeTemplate(result.data),
      bodyHtml: result.data.body_html,
      bodyText: result.data.body_text,
      renderedHtml: result.data.rendered_html,
      renderedText: result.data.rendered_text,
      steps: null,
    },
  };
}

export async function updateCdTemplate(
  token: string,
  key: string,
  body: { subject?: string; preheader?: string; body_html?: string; body_text?: string; cta_url?: string }
): Promise<BackendResult<EmailCampaignTemplate>> {
  const blocked = guard();
  if (blocked) return blocked;

  const result = await backendFetch<RawCdTemplate>(
    `${baseUrl()}${BASE_PATH}/templates/${encodeURIComponent(key)}`,
    { method: "PUT", headers: authHeaders(token), body: JSON.stringify(body) },
    "Cloud Decoded"
  );
  if (!result.ok) return result;
  return { ok: true, data: normalizeTemplate(result.data) };
}

async function postAction(token: string, path: string): Promise<BackendResult<{ status: string }>> {
  const blocked = guard();
  if (blocked) return blocked;
  return backendFetch<{ status: string }>(`${baseUrl()}${BASE_PATH}${path}`, { method: "POST", headers: authHeaders(token) }, "Cloud Decoded");
}

export const approveCdTemplate = (token: string, key: string) => postAction(token, `/templates/${encodeURIComponent(key)}/approve`);
export const retireCdTemplate = (token: string, key: string) => postAction(token, `/templates/${encodeURIComponent(key)}/retire`);
export const activateCdSequence = (token: string, key: string) => postAction(token, `/sequences/${encodeURIComponent(key)}/activate`);
export const deactivateCdSequence = (token: string, key: string) => postAction(token, `/sequences/${encodeURIComponent(key)}/deactivate`);

export async function getCdMetrics(token: string, sequenceKey?: string): Promise<BackendResult<EmailCampaignMetrics[]>> {
  const blocked = guard();
  if (blocked) return blocked;

  const url = new URL(`${baseUrl()}${BASE_PATH}/metrics`);
  if (sequenceKey) url.searchParams.set("sequence_key", sequenceKey);

  const result = await backendFetch<Parameters<typeof normalizeMetrics>[0][]>(url.toString(), { headers: authHeaders(token) }, "Cloud Decoded");
  if (!result.ok) return result;
  return { ok: true, data: result.data.map(normalizeMetrics) };
}
