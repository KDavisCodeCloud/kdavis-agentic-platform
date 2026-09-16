import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";
import { triggerImageGeneration } from "@/lib/trigger-image-generation";

const VALID_STATUSES = new Set(["pending_review", "approved", "rejected", "published"]);

// Replaces FastAPI's PATCH /internal/marketing/linkedin-queue/{queue_id} —
// see app/api/linkedin-queue/route.ts for why this moved off the
// never-deployed backend. That backend IS deployed now (Railway), and its
// image-generation-on-approval logic (api/routes/internal_marketing.py's
// _generate_and_gate_image_for_approved_row) needs this route to call it
// explicitly the moment status becomes 'approved' -- this route's own
// Supabase write is the only place that transition happens, and nothing on
// the backend side can otherwise observe it. See lib/trigger-image-generation.ts.
export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const { id } = await params;
  const body = await request.json();
  const { status, hitl_notes, scheduled_for } = body as {
    status?: string;
    hitl_notes?: string;
    scheduled_for?: string;
  };

  if (status !== undefined && !VALID_STATUSES.has(status)) {
    return NextResponse.json(
      { detail: `status must be one of ${Array.from(VALID_STATUSES).sort().join(", ")}` },
      { status: 400 }
    );
  }

  const update: Record<string, unknown> = {};
  if (status !== undefined) {
    update.status = status;
    update.hitl_reviewed_at = new Date().toISOString();
  }
  if (hitl_notes !== undefined) update.hitl_notes = hitl_notes;
  if (scheduled_for !== undefined) update.scheduled_for = scheduled_for;

  if (Object.keys(update).length === 0) {
    return NextResponse.json({ detail: "Provide at least one of status/hitl_notes/scheduled_for" }, { status: 400 });
  }

  const supabase = createAdminClient();
  // Never touches a published row — a decision already executed isn't
  // reversible through this endpoint, same rule as the FastAPI version.
  const { data, error } = await supabase
    .from("linkedin_content_queue")
    .update(update)
    .eq("id", id)
    .neq("status", "published")
    .select("id, status, hitl_notes, scheduled_for")
    .single();

  if (error || !data) {
    return NextResponse.json({ detail: "Row not found, or already published (immutable)" }, { status: 409 });
  }

  if (status === "approved") {
    // Fire-and-forget from this route's perspective (the FastAPI side
    // schedules its own background task and returns almost immediately) --
    // a slow/unreachable backend must never block or fail this approval,
    // which already succeeded in Supabase. Logged, not surfaced to the UI.
    await triggerImageGeneration([id]);
  }

  return NextResponse.json(data);
}
