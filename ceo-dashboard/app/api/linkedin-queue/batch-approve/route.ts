import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";

// Replaces FastAPI's POST /internal/marketing/linkedin-queue/batch-approve —
// see app/api/linkedin-queue/route.ts for why this moved off the
// never-deployed backend. Approves every pending_review row in one
// batch_month at once — the one-time action; scripts/dispatch_scheduled_posts.py's
// cron (unrelated to this dashboard, runs via GitHub Actions directly
// against Postgres) does the actual publishing later, on each row's own
// scheduled_for date.
export async function POST(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const body = await request.json();
  const { batch_month: batchMonth } = body as { batch_month?: string };
  if (!batchMonth) {
    return NextResponse.json({ detail: "batch_month is required" }, { status: 400 });
  }

  const supabase = createAdminClient();
  const { data, error } = await supabase
    .from("linkedin_content_queue")
    .update({ status: "approved", hitl_reviewed_at: new Date().toISOString() })
    .eq("batch_month", batchMonth)
    .eq("status", "pending_review")
    .select("id");

  if (error) {
    return NextResponse.json({ detail: error.message }, { status: 500 });
  }

  const approvedIds = (data ?? []).map((r) => r.id);
  return NextResponse.json({ batch_month: batchMonth, approved_count: approvedIds.length, approved_ids: approvedIds });
}
