import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";

// GAPS #34 (2026-11-14): what each outreach contact did on theclouddecoded.com
// after opening their ?ref= demo link. mse-api puts the ref on each Outreach
// card (demo_ref, computed server-side there); Cloud Decoded records the
// events (migration 060, cd_funnel_events, same Supabase project this client
// reads -- see linkedin-queue/route.ts for the same pattern).
//
// Events only. Never the workspaces/incidents tables: api/middleware/
// internal_auth.py's isolation rule for owner tooling. The server-recorded
// signup_completed / subscribed events already say whether a ref signed up
// and what tier it pays for.

// Mirrors core/funnel_events.py's _REF_RE.
const REF_RE = /^[A-Za-z0-9_-]{4,64}$/;
const MAX_REFS = 200;

type Activity = {
  demo_opened: number;
  incidents_viewed: number;
  fixes: number;
  signup_clicked: number;
  signed_up: boolean;
  paid_tier: string | null;
  checkout_tier: string | null;
  last_seen: string | null;
};

const empty = (): Activity => ({
  demo_opened: 0,
  incidents_viewed: 0,
  fixes: 0,
  signup_clicked: 0,
  signed_up: false,
  paid_tier: null,
  checkout_tier: null,
  last_seen: null,
});

export async function GET(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const refs = [
    ...new Set(
      (new URL(request.url).searchParams.get("refs") ?? "")
        .split(",")
        .map((r) => r.trim())
        .filter((r) => REF_RE.test(r)),
    ),
  ].slice(0, MAX_REFS);
  if (refs.length === 0) return NextResponse.json({ activity: {} });

  const supabase = createAdminClient();
  const { data, error } = await supabase
    .from("cd_funnel_events")
    .select("ref, event_name, properties, created_at")
    .eq("product_id", "cloud_decoded")
    .in("ref", refs)
    .order("created_at", { ascending: true })
    .limit(5000);
  if (error) return NextResponse.json({ detail: error.message }, { status: 500 });

  const activity: Record<string, Activity> = {};
  for (const row of data ?? []) {
    const a = (activity[row.ref] ??= empty());
    const tier = (row.properties as { tier?: string } | null)?.tier ?? null;
    switch (row.event_name) {
      case "demo_opened": a.demo_opened += 1; break;
      case "incident_viewed": a.incidents_viewed += 1; break;
      case "fix_approved":
      case "fix_resolved_manually": a.fixes += 1; break;
      case "signup_clicked": a.signup_clicked += 1; break;
      case "signup_completed": a.signed_up = true; break;
      case "checkout_started": a.checkout_tier = tier; break;
      case "subscribed": a.paid_tier = tier ?? "paid"; break;
    }
    a.last_seen = row.created_at;
  }
  return NextResponse.json({ activity });
}
