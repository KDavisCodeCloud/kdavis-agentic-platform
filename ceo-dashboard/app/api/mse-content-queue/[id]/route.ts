import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";

const VALID_STATUSES = new Set(["pending_review", "approved", "rejected", "sent"]);

// PATCH mse_social_content: approve/reject a post, or mark it sent once a
// human has actually posted the approved copy to Reddit/Facebook
// themselves. There is no automated posting client for either platform
// yet (Meta Business verification for Facebook, and Reddit API
// credentials, are both still open owner actions -- not code problems) --
// "sent" here is an honest manual confirmation, not a fabricated
// auto-publish.
export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const { id } = await params;
  const body = await request.json();
  const { status, hitl_notes } = body as { status?: string; hitl_notes?: string };

  if (status !== undefined && !VALID_STATUSES.has(status)) {
    return NextResponse.json(
      { detail: `status must be one of ${Array.from(VALID_STATUSES).sort().join(", ")}` },
      { status: 400 }
    );
  }

  const update: Record<string, unknown> = {};
  if (status !== undefined) {
    update.status = status;
    update.reviewed_at = new Date().toISOString();
    if (status === "sent") update.sent_at = new Date().toISOString();
  }
  if (hitl_notes !== undefined) update.hitl_notes = hitl_notes;

  if (Object.keys(update).length === 0) {
    return NextResponse.json({ detail: "Provide at least one of status/hitl_notes" }, { status: 400 });
  }

  const supabase = createAdminClient();
  // Never touches a row already marked sent -- a post that's actually
  // gone out is immutable through this endpoint, same rule as
  // linkedin-queue's "published" guard.
  const { data, error } = await supabase
    .from("mse_social_content")
    .update(update)
    .eq("id", id)
    .neq("status", "sent")
    .select("id, status, hitl_notes, reviewed_at, sent_at")
    .single();

  if (error || !data) {
    return NextResponse.json({ detail: "Row not found, or already sent (immutable)" }, { status: 409 });
  }

  return NextResponse.json(data);
}
