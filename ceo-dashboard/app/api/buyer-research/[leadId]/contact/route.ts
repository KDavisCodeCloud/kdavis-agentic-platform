import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Proxies POST /marketing/buyer-research/{lead_id}/contact. Saving a pasted
// LinkedIn profile creates the contact and triggers email pattern + SMTP +
// catch-all grading on the backend (background task -- the human is not made
// to wait on a stranger's mail server).
const API_BASE = process.env.NEXT_PUBLIC_MSE_API_URL ?? "http://localhost:8000";

export async function POST(
  request: NextRequest,
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
  const payload = await request.json().catch(() => null);
  if (!payload) return NextResponse.json({ detail: "Expected a JSON body" }, { status: 400 });

  try {
    const res = await fetch(
      `${API_BASE}/marketing/buyer-research/${encodeURIComponent(leadId)}/contact`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
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
