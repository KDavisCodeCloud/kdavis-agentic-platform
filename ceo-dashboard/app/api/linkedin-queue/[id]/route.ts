import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";

const VALID_STATUSES = new Set(["pending_review", "approved", "rejected", "published"]);

// Replaces FastAPI's PATCH /internal/marketing/linkedin-queue/{queue_id} —
// see app/api/linkedin-queue/route.ts for why this moved off the
// never-deployed backend.
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

  return NextResponse.json(data);
}
