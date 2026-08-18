import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// "Fire posts now" button — proxies to the Cloud Decoded FastAPI backend's
// POST /api/v1/marketing/linkedin-on-demand (agents/marketing/mkt_li1_linkedin_brand.py's
// generate_on_demand_posts), unlike the rest of app/api/linkedin-queue/*
// which reads/writes Supabase directly. Generation is real LLM drafting
// (MKT-LI1's full pillar/Opinion Matrix system) that only that backend can
// do — there's no way to do this as a same-origin Supabase write like
// list/approve/reject/reschedule. Session auth (requireRole) happens here;
// the backend's own X-API-Key is a server-to-server secret, never sent to
// the browser.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const body = await request.json().catch(() => ({}));
  const { count, pillar_focus: pillarFocus } = body as { count?: number; pillar_focus?: string | null };

  if (!count || !Number.isInteger(count) || count < 1 || count > 30) {
    return NextResponse.json({ detail: "count must be an integer between 1 and 30" }, { status: 400 });
  }

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { detail: "MARKETING_API_KEY is not configured on this deployment" },
      { status: 500 }
    );
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/marketing/linkedin-on-demand`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify({ count, pillar_focus: pillarFocus ?? null }),
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Could not reach the Cloud Decoded backend at ${API_BASE}: ${(err as Error).message}` },
      { status: 503 }
    );
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json({ detail: data.detail ?? `Generation failed: ${res.status}` }, { status: res.status });
  }

  const posts = (data.posts ?? []) as { id: string; pillar_name: string; topic: string; scheduled_for: string }[];
  return NextResponse.json({
    post_count: data.post_count ?? posts.length,
    posts: posts.map((p) => ({ id: p.id, pillar_name: p.pillar_name, topic: p.topic, scheduled_for: p.scheduled_for })),
  });
}
