import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Proxies to GET /thd-consulting/leads/export.csv and streams the CSV
// straight through -- "Export selected leads or all leads to CSV from
// within the dashboard" requirement. Filters (status/min_score) pass
// through as query params.
// Fixed 2026-09-16: this was reading NEXT_PUBLIC_API_URL (Cloud Decoded's
// own backend var) despite every comment in this file saying "microsaas-engine
// backend" -- .env.example has always declared a separate NEXT_PUBLIC_MSE_API_URL
// for exactly this. Root cause of the dashboard's "Not Found" errors on the
// Lead Pipeline / Cold Outreach Tracker panels: this route was calling Cloud
// Decoded's backend, which has no /marketing/leads or /thd-consulting routes at all.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  const { search } = new URL(request.url);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/thd-consulting/leads/export.csv${search}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Could not reach the microsaas-engine backend at ${API_BASE}: ${(err as Error).message}` },
      { status: 503 }
    );
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return NextResponse.json({ detail: data.detail ?? `CSV export failed: ${res.status}` }, { status: res.status });
  }

  const csv = await res.text();
  return new NextResponse(csv, {
    status: 200,
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": "attachment; filename=thd_consulting_leads.csv",
    },
  });
}
