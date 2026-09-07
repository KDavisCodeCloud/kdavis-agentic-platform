import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Manual "n8n is down, run it anyway" fallback for the Sunday
// lead_finder_workflow.json cron -- proxies straight to the same
// POST /marketing/leads/find that n8n's own "Trigger POST /marketing/leads/find"
// node calls, so a human clicking this button gets identical behavior to
// the scheduled run. Session auth (requireRole) happens here, same split
// as linkedin-queue/generate/route.ts: the backend's own MARKETING_API_KEY
// is a server-to-server secret, never sent to the browser.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const body = await request.json().catch(() => ({}));
  const { product_id: productId } = body as { product_id?: string };
  if (!productId) {
    return NextResponse.json({ detail: "product_id is required" }, { status: 400 });
  }

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/marketing/leads/find`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ product_id: productId }),
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Could not reach the microsaas-engine backend at ${API_BASE}: ${(err as Error).message}` },
      { status: 503 }
    );
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json({ detail: data.detail ?? `Triggering lead finder failed: ${res.status}` }, { status: res.status });
  }
  return NextResponse.json(data);
}
