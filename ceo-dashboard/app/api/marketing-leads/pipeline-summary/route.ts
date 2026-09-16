import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Real stage counts for the Sales Pipeline card (previously a static mock,
// per that card's own "not_built" status note) -- proxies to
// GET /marketing/leads/pipeline-summary on the microsaas-engine backend.
// Fixed 2026-09-16: this was reading NEXT_PUBLIC_API_URL (Cloud Decoded's
// own backend var) despite every comment in this file saying "microsaas-engine
// backend" -- .env.example has always declared a separate NEXT_PUBLIC_MSE_API_URL
// for exactly this. Root cause of the dashboard's "Not Found" errors on the
// Lead Pipeline / Cold Outreach Tracker panels: this route was calling Cloud
// Decoded's backend, which has no /marketing/leads or /thd-consulting routes at all.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  const productId = request.nextUrl.searchParams.get("product_id");
  const url = new URL(`${API_BASE}/marketing/leads/pipeline-summary`);
  if (productId) url.searchParams.set("product_id", productId);

  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${apiKey}` },
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
    return NextResponse.json({ detail: data.detail ?? `Fetching pipeline summary failed: ${res.status}` }, { status: res.status });
  }
  return NextResponse.json(data);
}
