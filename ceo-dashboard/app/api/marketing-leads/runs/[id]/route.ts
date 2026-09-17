import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Polling endpoint for a lead-finder run's live status -- proxies to
// GET /marketing/leads/runs/{run_id} on the microsaas-engine backend.
// New 2026-09-17: Kelvin reported "Run Lead Finder Now" gives no status
// bar (no elapsed time, no indication of what it's searching for, no
// ETA) -- confirmed the frontend never called this endpoint at all after
// triggering a run. LeadPipelinePanel.tsx now polls this on an interval
// while a run is pending/running.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const { id: runId } = await params;

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: "MARKETING_API_KEY is not configured on this deployment" }, { status: 500 });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/marketing/leads/runs/${encodeURIComponent(runId)}`, {
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
    return NextResponse.json({ detail: data.detail ?? `Fetching lead finder run failed: ${res.status}` }, { status: res.status });
  }
  return NextResponse.json(data);
}
