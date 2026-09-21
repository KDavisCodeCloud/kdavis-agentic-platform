import type { EmailCampaignTemplate, EmailCampaignTemplateDetail, EmailCampaignMetrics, MseCampaignStatus } from "@/lib/types";
import { backendFetch, type BackendResult } from "./http";
import { signMseAdminJwt } from "./mse-auth";

// MSE's backend (kdavis-microsaas-engine, a separate repo/Supabase project),
// contract documented in that repo's docs/internal/email-approval-api.md.
// That doc is explicit that this wraps the REAL mse_email_sequences table
// (one row per whole sequence, no per-step rows) rather than the clean
// per-step schema the original build plan assumed -- normalizeTemplate
// below reflects that reality, not the plan's aspiration.
//
// Auth: a self-signed admin-role JWT (see mse-auth.ts), signed with
// MSE_SUPABASE_JWT_SECRET -- a copy of the SAME secret already
// provisioned on mse-api, not a newly minted credential -- rather than a
// separate static API key. ceo-dashboard's signed-in user's session JWT
// is for a DIFFERENT Supabase project and cannot be forwarded here the
// way the Cloud Decoded feed forwards its own.
const BASE_PATH = "/marketing/internal";

export function isMseEnabled(): boolean {
  return process.env.EMAIL_CAMPAIGNS_MSE_ENABLED !== "false";
}

function baseUrl(): string | null {
  return process.env.NEXT_PUBLIC_MSE_API_URL || null;
}

interface RawMseTemplate {
  template_key: string;
  sequence_key: string;
  step_count: number;
  subject: string | null;
  preheader: string | null;
  status: string;
  origin: "generated" | "adapted_from_script";
  source_script: string | null;
  grounding_sources: unknown[];
  product: { id: string; slug: string; name: string; resolved: boolean };
  campaign_build_id: string | null;
  hitl_approved_by: string | null;
  hitl_approved_at: string | null;
  created_at: string;
}

function normalizeTemplate(raw: RawMseTemplate): EmailCampaignTemplate {
  return {
    source: "mse",
    templateKey: raw.template_key,
    sequenceKey: raw.sequence_key,
    stepNumber: null,
    subject: raw.subject,
    preheader: raw.preheader,
    status: raw.status as EmailCampaignTemplate["status"],
    origin: raw.origin,
    sourceScript: raw.source_script,
    ctaUrl: null,
    skipIf: null,
    approvedAt: raw.hitl_approved_at,
    approvedBy: raw.hitl_approved_by,
    productLabel: raw.product.resolved ? `${raw.product.name} (${raw.product.slug})` : `Unresolved product id ${raw.product.id}`,
    productResolved: raw.product.resolved,
    createdAt: raw.created_at,
  };
}

function guard(): { ok: false; status: number; error: string } | null {
  if (!isMseEnabled()) {
    return { ok: false, status: 503, error: "MSE email feed is disabled (EMAIL_CAMPAIGNS_MSE_ENABLED=false)" };
  }
  if (!baseUrl()) {
    return { ok: false, status: 500, error: "NEXT_PUBLIC_MSE_API_URL is not configured on this deployment" };
  }
  if (!process.env.MSE_SUPABASE_JWT_SECRET) {
    return { ok: false, status: 500, error: "MSE_SUPABASE_JWT_SECRET is not configured on this deployment" };
  }
  return null;
}

function authHeaders(): HeadersInit {
  return { Authorization: `Bearer ${signMseAdminJwt()}`, "Content-Type": "application/json" };
}

export async function listMseTemplates(
  opts: { status?: string; productId?: string } = {}
): Promise<BackendResult<EmailCampaignTemplate[]>> {
  const blocked = guard();
  if (blocked) return blocked;

  const url = new URL(`${baseUrl()}${BASE_PATH}/email-templates`);
  if (opts.status) url.searchParams.set("status", opts.status);
  if (opts.productId) url.searchParams.set("product_id", opts.productId);

  const result = await backendFetch<{ templates: RawMseTemplate[] }>(url.toString(), { headers: authHeaders() }, "MSE");
  if (!result.ok) return result;
  return { ok: true, data: result.data.templates.map(normalizeTemplate) };
}

export async function getMseTemplate(key: string): Promise<BackendResult<EmailCampaignTemplateDetail>> {
  const blocked = guard();
  if (blocked) return blocked;

  const result = await backendFetch<RawMseTemplate & { steps: unknown[] }>(
    `${baseUrl()}${BASE_PATH}/email-templates/${encodeURIComponent(key)}`,
    { headers: authHeaders() },
    "MSE"
  );
  if (!result.ok) return result;
  return {
    ok: true,
    data: { ...normalizeTemplate(result.data), bodyHtml: null, bodyText: null, renderedHtml: null, renderedText: null, steps: result.data.steps },
  };
}

async function postAction(path: string): Promise<BackendResult<Record<string, unknown>>> {
  const blocked = guard();
  if (blocked) return blocked;
  return backendFetch<Record<string, unknown>>(`${baseUrl()}${BASE_PATH}${path}`, { method: "POST", headers: authHeaders() }, "MSE");
}

export const approveMseTemplate = (key: string) => postAction(`/email-templates/${encodeURIComponent(key)}/approve`);
export const retireMseTemplate = (key: string) => postAction(`/email-templates/${encodeURIComponent(key)}/retire`);

export async function getMseCampaignStatus(): Promise<BackendResult<MseCampaignStatus>> {
  const blocked = guard();
  if (blocked) return blocked;

  const result = await backendFetch<{
    products: Array<{ product_id: string; slug: string; name: string; product_status: string; positioning_status: string; positioning_version: number | null }>;
    email_sequences_total: number;
    email_sequences_unattributable: number;
    note?: string;
  }>(`${baseUrl()}${BASE_PATH}/campaign-status`, { headers: authHeaders() }, "MSE");
  if (!result.ok) return result;
  return {
    ok: true,
    data: {
      products: result.data.products.map((p) => ({
        productId: p.product_id, slug: p.slug, name: p.name,
        productStatus: p.product_status, positioningStatus: p.positioning_status, positioningVersion: p.positioning_version,
      })),
      emailSequencesTotal: result.data.email_sequences_total,
      emailSequencesUnattributable: result.data.email_sequences_unattributable,
      note: result.data.note ?? null,
    },
  };
}

export async function getMseMetrics(productId?: string): Promise<BackendResult<EmailCampaignMetrics[]>> {
  const blocked = guard();
  if (blocked) return blocked;

  const url = new URL(`${baseUrl()}${BASE_PATH}/email-metrics`);
  if (productId) url.searchParams.set("product_id", productId);

  const result = await backendFetch<{
    sends: number | null; clicks: number | null; unsubscribes: number | null; conversions: number | null; revenue: number | null; note?: string;
  }>(url.toString(), { headers: authHeaders() }, "MSE");
  if (!result.ok) return result;
  return {
    ok: true,
    data: [{
      source: "mse", sequenceKey: null,
      sends: result.data.sends, clicks: result.data.clicks, unsubscribes: result.data.unsubscribes,
      conversions: result.data.conversions, revenueUsd: result.data.revenue, note: result.data.note ?? null,
    }],
  };
}
