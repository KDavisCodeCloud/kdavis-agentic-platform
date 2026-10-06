import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Proxies every /marketing/outreach/* route on the microsaas-engine backend:
// summary, drafts, drafts/{id}/edit, ready-to-paste, ready-to-paste/{id}/mark,
// conversations, conversations/{leadId}/stage.
//
// ONE catch-all rather than seven near-identical route files. The auth check,
// the API-key guard and the upstream error handling are the same for all of
// them, and seven copies is how one of them ends up subtly different -- which
// is exactly the class of bug that put a second approval path in this system.
//
// NEXT_PUBLIC_MSE_API_URL, not NEXT_PUBLIC_API_URL: the latter is Cloud
// Decoded's own backend and has no /marketing routes at all, which caused the
// "Not Found" errors on the lead panels in 2026-09.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

// Only these may be reached through the proxy. An allowlist rather than
// blind forwarding: a catch-all that passes anything through would expose
// every other /marketing route to the dashboard session.
const ALLOWED = [
  /^summary$/,
  /^drafts$/,
  /^drafts\/[A-Za-z0-9-]+\/edit$/,
  /^ready-to-paste$/,
  /^ready-to-paste\/[A-Za-z0-9-]+\/mark$/,
  /^conversations$/,
  /^conversations\/[A-Za-z0-9-]+\/stage$/,
];

async function proxy(request: NextRequest, path: string[], method: "GET" | "POST") {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const suffix = (path ?? []).join("/");
  if (!ALLOWED.some((re) => re.test(suffix))) {
    return NextResponse.json({ detail: `Unsupported outreach path: ${suffix}` }, { status: 404 });
  }

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { detail: "MARKETING_API_KEY is not configured on this deployment" },
      { status: 500 }
    );
  }

  const { search } = new URL(request.url);
  const init: RequestInit = {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
    },
    cache: "no-store",
  };
  if (method === "POST") {
    init.body = await request.text();
  }

  try {
    const res = await fetch(`${API_BASE}/marketing/outreach/${suffix}${search}`, init);
    const body = await res
      .json()
      .catch(() => ({ detail: "Upstream returned a non-JSON body" }));
    return NextResponse.json(body, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { detail: e instanceof Error ? e.message : "Upstream request failed" },
      { status: 502 }
    );
  }
}

export async function GET(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(request, path, "GET");
}

export async function POST(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(request, path, "POST");
}
