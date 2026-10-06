import { NextRequest, NextResponse } from "next/server";
import { requireRole, getSupabaseAccessToken } from "@/lib/api-auth";

// Proxies the APPROVE and REJECT endpoints, which live under /outreach/ on the
// microsaas-engine backend -- not /marketing/outreach/ -- and are guarded by
// _require_admin(request), i.e. the signed-in admin's OWN Supabase JWT rather
// than the static MARKETING_API_KEY.
//
// Kept separate from app/api/outreach/[...path] for that reason: the two use
// different credentials, and a single proxy that chose between them per path
// would make it easy to send the wrong one. Approval is also the one action
// here that causes a real email to a stranger, so it is deliberately the
// endpoint that requires a human's own session and cannot be driven by a
// server-side key.
//
// The HITL state machine itself (_approval_target_status) stays in the
// backend. This forwards; it decides nothing.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

const ACTIONS = new Set(["approve", "reject"]);

export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ sequenceId: string; action: string }> }
) {
  const { sequenceId, action } = await ctx.params;

  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  if (!ACTIONS.has(action)) {
    return NextResponse.json({ detail: `Unsupported action: ${action}` }, { status: 404 });
  }
  if (!/^[A-Za-z0-9-]+$/.test(sequenceId)) {
    return NextResponse.json({ detail: "Invalid sequence id" }, { status: 400 });
  }

  const token = await getSupabaseAccessToken();
  if (!token) {
    return NextResponse.json(
      { detail: "No Supabase session token; sign in again" },
      { status: 401 }
    );
  }

  try {
    const res = await fetch(
      `${API_BASE}/outreach/dm-sequences/${sequenceId}/${action}`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: await request.text(),
        cache: "no-store",
      }
    );
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
