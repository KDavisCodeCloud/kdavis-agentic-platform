import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { listCdTemplates, getCdMetrics } from "../cloud-decoded-client";

const RAW_TEMPLATE = {
  template_key: "onboarding_step1_connect_stack",
  sequence_key: "onboarding",
  step_number: 1,
  subject: "Still time to connect your stack",
  preheader: "Nothing runs until at least one system is connected.",
  status: "pending_approval",
  origin: "generated" as const,
  source_script: null,
  cta_url: "https://theclouddecoded.com/dashboard?tab=connections",
  skip_if: "connected_anything",
  approved_at: null,
  approved_by: null,
  product: "cloud-decoded",
};

describe("cloud-decoded-client", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.test");
    vi.stubEnv("EMAIL_CAMPAIGNS_CD_ENABLED", "true");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("normalizes the backend's snake_case shape into the dashboard's camelCase type", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [RAW_TEMPLATE] }));

    const result = await listCdTemplates("test-token", { statusFilter: "pending_approval" });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data[0]).toMatchObject({
        source: "cloud-decoded",
        templateKey: "onboarding_step1_connect_stack",
        sequenceKey: "onboarding",
        stepNumber: 1,
        status: "pending_approval",
        productLabel: "cloud-decoded",
        productResolved: true,
      });
    }
  });

  it("forwards the caller's session token as a Bearer header, never a static key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);

    await listCdTemplates("the-users-own-jwt");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer the-users-own-jwt");
  });

  it("refuses to call the backend at all when the feed is disabled", async () => {
    vi.stubEnv("EMAIL_CAMPAIGNS_CD_ENABLED", "false");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await listCdTemplates("test-token");
    expect(result).toEqual({ ok: false, status: 503, error: "Cloud Decoded email feed is disabled (EMAIL_CAMPAIGNS_CD_ENABLED=false)" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("500s cleanly when NEXT_PUBLIC_API_URL is unset, rather than fetching an invalid URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await listCdTemplates("test-token");
    expect(result).toEqual({ ok: false, status: 500, error: "NEXT_PUBLIC_API_URL is not configured on this deployment" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("normalizes metrics rows including the revenue estimate field name change", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ sequence_key: "onboarding", sends: 42, clicks: 11, unsubscribes: 3, conversions: 2, revenue_usd_estimate: 598 }],
    }));

    const result = await getCdMetrics("test-token");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data[0]).toEqual({
        source: "cloud-decoded", sequenceKey: "onboarding",
        sends: 42, clicks: 11, unsubscribes: 3, conversions: 2, revenueUsd: 598, note: null,
      });
    }
  });
});
