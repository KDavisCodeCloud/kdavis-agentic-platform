import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Proxies GET /marketing/buyer-research on the microsaas-engine backend.
// Same shape and auth as app/api/marketing-leads/* and app/api/thd-consulting/*:
// NEXT_PUBLIC_MSE_API_URL (NOT NEXT_PUBLIC_API_URL -- that is Cloud Decoded's
// own backend and has no /marketing routes at all, which was the root cause of
// the "Not Found" errors on the lead panels in 2026-09).
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { detail: "MARKETING_API_KEY is not configured on this deployment" },
      { status: 500 }
    );
  }

  const { search } = new URL(request.url);
  try {
    const res = await fetch(`${API_BASE}/marketing/buyer-research${search}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({ detail: "Upstream returned a non-JSON body" }));
    return NextResponse.json(body, { status: res.status });
  } catch (err) {
    // The MSE backend is not always reachable (see
    // docs/railway-start-command.md in kdavis-microsaas-engine -- GitHub
    // deploys are currently blocked). Say so plainly rather than rendering an
    // empty lane that looks like "no work to do".
    return NextResponse.json(
      { detail: `Could not reach the microsaas-engine backend at ${API_BASE}: ${String(err)}` },
      { status: 502 }
    );
  }
}
