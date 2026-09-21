import { describe, it, expect, vi, afterEach } from "vitest";

const requireRoleMock = vi.fn();
const getSupabaseAccessTokenMock = vi.fn();

vi.mock("@/lib/api-auth", () => ({
  requireRole: (...args: unknown[]) => requireRoleMock(...args),
  getSupabaseAccessToken: () => getSupabaseAccessTokenMock(),
}));

import { requireAdmin, requireAdminWithToken, toResponse } from "../route-helpers";

describe("route-helpers", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("requireAdmin only ever asks for the admin role -- no hitl role exists on either backend yet", async () => {
    requireRoleMock.mockResolvedValue({ ok: true });
    await requireAdmin();
    expect(requireRoleMock).toHaveBeenCalledWith(["admin"]);
  });

  it("requireAdmin rejects a non-admin role with the backend's own status/message", async () => {
    requireRoleMock.mockResolvedValue({ ok: false, status: 403, error: "Role 'rnd' is not permitted" });

    const result = await requireAdmin();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      const body = await result.response.json();
      expect(result.response.status).toBe(403);
      expect(body.detail).toBe("Role 'rnd' is not permitted");
    }
  });

  it("requireAdminWithToken 401s when the role check passes but there is no session token to forward", async () => {
    requireRoleMock.mockResolvedValue({ ok: true });
    getSupabaseAccessTokenMock.mockResolvedValue(null);

    const result = await requireAdminWithToken();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.response.status).toBe(401);
    }
  });

  it("requireAdminWithToken returns the real session token on success, for forwarding to Cloud Decoded", async () => {
    requireRoleMock.mockResolvedValue({ ok: true });
    getSupabaseAccessTokenMock.mockResolvedValue("the-users-own-jwt");

    const result = await requireAdminWithToken();
    expect(result).toEqual({ ok: true, token: "the-users-own-jwt" });
  });

  it("requireAdminWithToken short-circuits on a failed role check without fetching a token at all", async () => {
    requireRoleMock.mockResolvedValue({ ok: false, status: 403, error: "nope" });

    await requireAdminWithToken();
    expect(getSupabaseAccessTokenMock).not.toHaveBeenCalled();
  });

  it("toResponse turns a backend error result into the matching JSON status", async () => {
    const res = toResponse({ ok: false, status: 409, error: "already activated" });
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ detail: "already activated" });
  });

  it("toResponse passes through successful data untouched", async () => {
    const res = toResponse({ ok: true, data: { foo: "bar" } });
    expect(await res.json()).toEqual({ foo: "bar" });
  });
});
