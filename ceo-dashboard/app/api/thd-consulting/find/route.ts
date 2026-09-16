import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Proxies to POST /thd-consulting/scrape/find on the microsaas-engine
// backend (api/routers/thd_consulting.py) -- same split as
// app/api/marketing-leads/find/route.ts: session auth (requireRole)
// happens here, the backend's own MARKETING_API_KEY is a server-to-server
// secret that never reaches the browser. THD Consulting is Kelvin's own
// consulting line, not an MSE product, so this is admin-only (no
// "marketing" role) unlike marketing-leads/find.
// Fixed 2026-09-16: this was reading NEXT_PUBLIC_API_URL (Cloud Decoded's
// own backend var) despite every comment in this file saying "microsaas-engine
// backend" -- .env.example has always declared a separate NEXT_PUBLIC_MSE_API_URL
// for exactly this. Root cause of the dashboard's "Not Found" errors on the
// Lead Pipeline / Cold Outreach Tracker panels: this route was calling Cloud
// Decoded's backend, which has no /marketing/leads or /thd-consulting routes at all.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const body = await request.json().catch(() => ({}));

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/thd-consulting/scrape/find`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify(body),
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
    return NextResponse.json({ detail: data.detail ?? `Triggering lead scout failed: ${res.status}` }, { status: res.status });
  }
  return NextResponse.json(data);
}
