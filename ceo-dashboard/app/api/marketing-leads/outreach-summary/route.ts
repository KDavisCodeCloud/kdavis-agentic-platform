import { NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Real per-product sent/meetings counts for the Cold Outreach Tracker card
// (previously a static mock) -- proxies to
// GET /marketing/leads/outreach-summary on the microsaas-engine backend.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET() {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/marketing/leads/outreach-summary`, {
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
    return NextResponse.json({ detail: data.detail ?? `Fetching outreach summary failed: ${res.status}` }, { status: res.status });
  }
  return NextResponse.json(data);
}
