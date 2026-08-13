import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";

// MKT-V1's Reddit/Facebook output (mse_social_content, kdavis-microsaas-engine)
// previously dead-ended in Postgres -- nothing read it, no review step
// existed. This mirrors linkedin-queue/route.ts's pattern exactly: same
// shared Supabase project (microsaas-prod), service-role client since
// mse_social_content's RLS is admin-only.
export async function GET(request: NextRequest) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const { searchParams } = new URL(request.url);
  const productId = searchParams.get("product_id");
  const status = searchParams.get("status");
  const platform = searchParams.get("platform");

  const supabase = createAdminClient();
  let query = supabase
    .from("mse_social_content")
    .select("id, product_id, campaign_build_id, platform, title, body, status, hitl_notes, reviewed_at, sent_at, created_at")
    .order("created_at", { ascending: false });

  if (productId) query = query.eq("product_id", productId);
  if (status) query = query.eq("status", status);
  if (platform) query = query.eq("platform", platform);

  const { data, error } = await query;
  if (error) {
    return NextResponse.json({ detail: error.message }, { status: 500 });
  }

  return NextResponse.json({ posts: data ?? [] });
}
