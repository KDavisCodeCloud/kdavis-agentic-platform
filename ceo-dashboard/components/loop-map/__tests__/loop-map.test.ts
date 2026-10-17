import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { CLS, LAB, SPR, laneHref, openHoles, spriteRects, target, waitingCards, type Product, type Station } from "../model";
import { isAllowedLoopMapPath } from "@/lib/loop-map-paths";

const requireRoleMock = vi.fn();
vi.mock("@/lib/api-auth", () => ({ requireRole: (...a: unknown[]) => requireRoleMock(...a) }));
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({ auth: { getUser: async () => ({ data: { user: { email: "kelvin@example.com" } } }) } }),
}));

const station = (n: number, over: Partial<Station> = {}): Station => ({
  step_order: n, name: `Step ${n}`, owner: "auto", description: "", next_action: "", lane_link: null,
  target_hint: null, rule_key: "x", status: "working", count: null, evidence: "ok", evidence_at: null,
  evidence_link: null, status_since: null, history: [], done: false, done_at: null, ...over,
});
const product = (stations: Station[], over: Partial<Product> = {}): Product => ({
  product_id: "p", slug: "p", name: "Prod", playbook: "content", playbook_line: "", verdict: { tone: "ok", title: "", body: "" },
  math: [], chips: [], lap: 1, laps_finished: 0, last_lap_at: null, stations, notes: [], funnel: null, ...over,
});

describe("loop map model", () => {
  it("keeps the reference sprite: 8x10 grid -> 32x40 svg in 4px cells", () => {
    expect(SPR).toHaveLength(10);
    expect(SPR.every((r) => r.length === 8)).toBe(true);
    const rects = spriteRects();
    expect(Math.max(...rects.map((r) => r.x))).toBe(28);
    expect(Math.max(...rects.map((r) => r.y))).toBe(36);
  });

  it("maps every status to a class and label, and unknown is never the green class", () => {
    for (const s of ["working", "not_proven", "waiting_on_you", "blocked", "not_built", "unknown"] as const) {
      expect(CLS[s]).toBeTruthy();
      expect(LAB[s]).toBeTruthy();
    }
    expect(CLS.unknown).not.toBe(CLS.working);
  });

  it("puts the worker at the first unchecked desk, or the flag when all are done", () => {
    expect(target(product([station(1, { done: true }), station(2), station(3)]))).toBe(1);
    expect(target(product([station(1, { done: true }), station(2, { done: true })]))).toBe(2);
  });

  it("counts only open holes", () => {
    const p = product([station(1)], {
      notes: [
        { id: "a", product_id: "p", step_order: 1, lap: 1, kind: "hole", text: "x", created_at: "", created_by: null, resolved_at: null },
        { id: "b", product_id: "p", step_order: 1, lap: 1, kind: "hole", text: "x", created_at: "", created_by: null, resolved_at: "2026-10-17" },
        { id: "c", product_id: "p", step_order: 1, lap: 1, kind: "note", text: "x", created_at: "", created_by: null, resolved_at: null },
      ],
    });
    expect(openHoles(p)).toBe(1);
  });

  it("waiting strip names the first blocked or waiting desk per product", () => {
    const cards = waitingCards([
      product([station(1), station(2, { status: "waiting_on_you", name: "Approve" }), station(3, { status: "blocked" })]),
      product([station(1)], { slug: "q" }),
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].title).toBe("PROD WAITS ON YOU AT APPROVE");
    expect(cards[0].cls).toBe("you");
  });

  it("links lanes inside the dashboard", () => {
    expect(laneHref("/marketing#outreach")).toBe("/dashboard/marketing#outreach");
    expect(laneHref(null)).toBeNull();
  });
});

describe("loop map proxy allowlist", () => {
  const P = "9b6c8f36-985f-4d7a-a416-c40da89e23af";
  it("allows only the map read and the five desk write paths", () => {
    expect(isAllowedLoopMapPath("GET", "")).toBe(true);
    expect(isAllowedLoopMapPath("POST", `${P}/steps/3/complete`)).toBe(true);
    expect(isAllowedLoopMapPath("POST", `${P}/steps/3/undo`)).toBe(true);
    expect(isAllowedLoopMapPath("POST", `${P}/laps/complete`)).toBe(true);
    expect(isAllowedLoopMapPath("POST", `${P}/laps/reset`)).toBe(true);
    expect(isAllowedLoopMapPath("POST", `${P}/notes`)).toBe(true);
    expect(isAllowedLoopMapPath("POST", `notes/${P}/resolve`)).toBe(true);
  });
  it("blocks the snapshot and playbook routes and anything else", () => {
    expect(isAllowedLoopMapPath("POST", "snapshot")).toBe(false);
    expect(isAllowedLoopMapPath("POST", `products/${P}/playbook`)).toBe(false);
    expect(isAllowedLoopMapPath("GET", `${P}/notes`)).toBe(false);
    expect(isAllowedLoopMapPath("POST", `${P}/steps/3/complete/../../x`)).toBe(false);
  });
});

describe("loop map proxy route", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    process.env.MARKETING_API_KEY = "k";
    process.env.NEXT_PUBLIC_MSE_API_URL = "https://mse.example";
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
  });
  afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); });

  it("rejects a non-admin before reaching the backend", async () => {
    requireRoleMock.mockResolvedValue({ ok: false, status: 403, error: "Role 'marketing' is not permitted" });
    const { GET } = await import("@/app/api/loop-map/[[...path]]/route");
    const res = await GET(new Request("http://x/api/loop-map") as never, { params: Promise.resolve({}) });
    expect(res.status).toBe(403);
    expect(requireRoleMock).toHaveBeenCalledWith(["admin"]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards with the API key and the session's email as the actor", async () => {
    requireRoleMock.mockResolvedValue({ ok: true });
    const { POST } = await import("@/app/api/loop-map/[[...path]]/route");
    const P = "9b6c8f36-985f-4d7a-a416-c40da89e23af";
    const res = await POST(new Request("http://x", { method: "POST", body: "{}" }) as never,
      { params: Promise.resolve({ path: [P, "steps", "2", "complete"] }) });
    expect(res.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`https://mse.example/marketing/loop-map/${P}/steps/2/complete`);
    expect(init.headers.Authorization).toBe("Bearer k");
    expect(init.headers["X-Loop-Actor"]).toBe("kelvin@example.com");
  });
});
