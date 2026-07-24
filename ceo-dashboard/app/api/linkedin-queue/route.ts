import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";

// Replaces the FastAPI GET /internal/marketing/linkedin-queue call — that
// backend has never been deployed anywhere publicly reachable (confirmed
// 2026-07-24), which is why the dashboard's LinkedIn batch panel showed
// "Failed to fetch". This runs as a Vercel serverless function directly
// alongside the rest of ceo-dashboard, no separate backend needed for
// list/approve/reject/reschedule.
export async function GET(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const { searchParams } = new URL(request.url);
  const batchMonth = searchParams.get("batch_month");
  const status = searchParams.get("status");

  const supabase = createAdminClient();
  let query = supabase
    .from("linkedin_content_queue")
    .select(
      "id, pillar, pillar_name, topic, post_copy, hook_variants, format, image_brief, hitl_tier, status, hitl_notes, batch_month, scheduled_for, published_at, created_at"
    )
    .order("scheduled_for", { ascending: true, nullsFirst: false })
    .order("created_at", { ascending: true });

  if (batchMonth) query = query.eq("batch_month", batchMonth);
  if (status) query = query.eq("status", status);

  const { data, error } = await query;
  if (error) {
    return NextResponse.json({ detail: error.message }, { status: 500 });
  }

  return NextResponse.json({ posts: data ?? [] });
}
