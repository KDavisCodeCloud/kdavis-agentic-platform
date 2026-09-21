import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import jwt from "jsonwebtoken";
import { listMseTemplates, getMseCampaignStatus } from "../mse-client";

const TEST_JWT_SECRET = "test-mse-supabase-jwt-secret";

const RAW_TEMPLATE = {
  template_key: "seq-1", sequence_key: "seq-1", step_count: 5,
  subject: "hello", preheader: null, status: "pending_hitl",
  origin: "generated" as const, source_script: null, grounding_sources: [],
  product: { id: "prod-1", slug: "tradesdesk", name: "TradesDesk", resolved: true },
  campaign_build_id: null, hitl_approved_by: null, hitl_approved_at: null,
  created_at: "2026-09-21T00:00:00Z",
};

describe("mse-client", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_MSE_API_URL", "https://mse.example.test");
    vi.stubEnv("MSE_SUPABASE_JWT_SECRET", TEST_JWT_SECRET);
    vi.stubEnv("EMAIL_CAMPAIGNS_MSE_ENABLED", "true");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("normalizes a resolved product into a readable label", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ templates: [RAW_TEMPLATE] }) }));

    const result = await listMseTemplates();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data[0].productLabel).toBe("TradesDesk (tradesdesk)");
      expect(result.data[0].productResolved).toBe(true);
      expect(result.data[0].stepNumber).toBeNull(); // whole-sequence rows, not per-step
    }
  });

  it("flags an unresolved product id instead of showing a blank name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [{ ...RAW_TEMPLATE, product: { id: "orphan-id", slug: "", name: "", resolved: false } }] }),
    }));

    const result = await listMseTemplates();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data[0].productResolved).toBe(false);
      expect(result.data[0].productLabel).toContain("orphan-id");
    }
  });

  it("signs its own admin JWT with the shared MSE Supabase secret, not a forwarded user session token", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ templates: [] }) });
    vi.stubGlobal("fetch", fetchMock);

    await listMseTemplates();

    const [, init] = fetchMock.mock.calls[0];
    const token = (init.headers as Record<string, string>).Authorization.replace("Bearer ", "");
    const decoded = jwt.verify(token, TEST_JWT_SECRET) as jwt.JwtPayload;
    expect(decoded.aud).toBe("authenticated");
    expect(decoded.app_metadata).toEqual({ role: "admin" });
  });

  it("500s when MSE_SUPABASE_JWT_SECRET is not configured, rather than sending an unauthenticated request", async () => {
    vi.stubEnv("MSE_SUPABASE_JWT_SECRET", "");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await listMseTemplates();
    expect(result).toEqual({ ok: false, status: 500, error: "MSE_SUPABASE_JWT_SECRET is not configured on this deployment" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses to call the backend when the feed is disabled via the kill switch", async () => {
    vi.stubEnv("EMAIL_CAMPAIGNS_MSE_ENABLED", "false");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await getMseCampaignStatus();
    expect(result).toEqual({ ok: false, status: 503, error: "MSE email feed is disabled (EMAIL_CAMPAIGNS_MSE_ENABLED=false)" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
