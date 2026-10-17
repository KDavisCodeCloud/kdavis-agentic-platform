import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";
import { createClient } from "@/lib/supabase/server";
import { isAllowedLoopMapPath } from "@/lib/loop-map-paths";

// Proxies the Loop Map's routes on the microsaas-engine backend
// (api/routers/loop_map.py): GET the map, and the five write paths a desk
// click can make. Same shape as app/api/outreach/[...path]: admin role checked
// here, MARKETING_API_KEY added server-side, an allowlist instead of blind
// forwarding (lib/loop-map-paths.ts).
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

async function proxy(request: NextRequest, path: string[] | undefined, method: "GET" | "POST") {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const suffix = (path ?? []).join("/");
  if (!isAllowedLoopMapPath(method, suffix)) {
    return NextResponse.json({ detail: `Unsupported loop-map path: ${method} ${suffix}` }, { status: 404 });
  }

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  // completed_by / created_by: the signed-in admin, taken from the session
  // here -- never from the request body, which the browser controls.
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  const init: RequestInit = {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      ...(user?.email ? { "X-Loop-Actor": user.email } : {}),
      ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
    },
    cache: "no-store",
  };
  if (method === "POST") init.body = (await request.text()) || "{}";

  try {
    const res = await fetch(`${API_BASE}/marketing/loop-map${suffix ? `/${suffix}` : ""}`, init);
    const body = await res.json().catch(() => ({ detail: "Upstream returned a non-JSON body" }));
    return NextResponse.json(body, { status: res.status });
  } catch (e) {
    return NextResponse.json({ detail: e instanceof Error ? e.message : "Upstream request failed" }, { status: 502 });
  }
}

export async function GET(request: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(request, path, "GET");
}

export async function POST(request: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(request, path, "POST");
}
