import { describe, it, expect, vi, afterEach } from "vitest";
import { backendFetch } from "../http";

describe("backendFetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns ok:true with parsed JSON on a 200 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ hello: "world" }),
    }));

    const result = await backendFetch<{ hello: string }>("https://example.test/x", {}, "Test");
    expect(result).toEqual({ ok: true, data: { hello: "world" } });
  });

  it("returns ok:false with the backend's detail message on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Role 'rnd' is not permitted" }),
    }));

    const result = await backendFetch("https://example.test/x", {}, "Test");
    expect(result).toEqual({ ok: false, status: 403, error: "Role 'rnd' is not permitted" });
  });

  it("falls back to a generic message when the error body has no detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    }));

    const result = await backendFetch("https://example.test/x", {}, "Test");
    expect(result).toEqual({ ok: false, status: 500, error: "Test request failed: 500" });
  });

  it("degrades a network failure to a 503, never throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

    const result = await backendFetch("https://example.test/x", {}, "Test");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.status).toBe(503);
      expect(result.error).toContain("Could not reach the Test backend");
      expect(result.error).toContain("ECONNREFUSED");
    }
  });
});
