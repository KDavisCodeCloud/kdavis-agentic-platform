import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Proxies POST /marketing/buyer-research/{lead_id}/skip -- moves a company out
// of the lane as 'none_found' without deleting it, the same terminal state the
// automated retry reaches.
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ leadId: string }> }
) {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { detail: "MARKETING_API_KEY is not configured on this deployment" },
      { status: 500 }
    );
  }

  const { leadId } = await params;
  try {
    const res = await fetch(
      `${API_BASE}/marketing/buyer-research/${encodeURIComponent(leadId)}/skip`,
      { method: "POST", headers: { Authorization: `Bearer ${apiKey}` } }
    );
    const body = await res.json().catch(() => ({ detail: "Upstream returned a non-JSON body" }));
    return NextResponse.json(body, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { detail: `Could not reach the microsaas-engine backend at ${API_BASE}: ${String(err)}` },
      { status: 502 }
    );
  }
}
