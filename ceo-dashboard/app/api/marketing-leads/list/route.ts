import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// The actual individual lead rows (name/title/company/email/linkedin_url/
// source/status) -- proxies to GET /marketing/leads on the microsaas-engine
// backend. Added 2026-09-23: the Lead Pipeline panel only ever showed
// aggregate stage counts (pipeline-summary) -- Kelvin ran the lead finder
// for Cloud Decoded and had no way to actually see or work the leads it
// found, only a "NEW: 3" tile with nothing behind it.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  const params = request.nextUrl.searchParams;
  const url = new URL(`${API_BASE}/marketing/leads`);
  for (const key of ["product_id", "status", "source", "email_status", "limit", "offset"]) {
    const value = params.get(key);
    if (value) url.searchParams.set(key, value);
  }

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
    return NextResponse.json({ detail: data.detail ?? `Fetching leads failed: ${res.status}` }, { status: res.status });
  }
  return NextResponse.json(data);
}
