import { NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Manual fallback for the hourly outreach-sender-workflow.json cron --
// proxies to the same POST /marketing/send-sequences that workflow calls
// (MKT-O5, touch_1/touch_2 email sends). No body: the backend endpoint
// itself takes none, it just sends whatever's due.
// Fixed 2026-09-16: this was reading NEXT_PUBLIC_API_URL (Cloud Decoded's
// own backend var) despite every comment in this file saying "microsaas-engine
// backend" -- .env.example has always declared a separate NEXT_PUBLIC_MSE_API_URL
// for exactly this. Root cause of the dashboard's "Not Found" errors on the
// Lead Pipeline / Cold Outreach Tracker panels: this route was calling Cloud
// Decoded's backend, which has no /marketing/leads or /thd-consulting routes at all.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function POST() {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/marketing/send-sequences`, {
      method: "POST",
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
    return NextResponse.json({ detail: data.detail ?? `Triggering sequence send failed: ${res.status}` }, { status: res.status });
  }
  return NextResponse.json(data);
}
