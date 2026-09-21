import { NextResponse } from "next/server";
import { requireAdminWithToken } from "@/lib/email-campaigns/route-helpers";
import { listCdTemplates } from "@/lib/email-campaigns/cloud-decoded-client";
import { listMseTemplates } from "@/lib/email-campaigns/mse-client";

// Backs the sidebar nav badge. Aggregates both feeds' pending-approval
// counts into one number; a feed that's down or disabled contributes 0
// rather than failing the whole badge (this is a lightweight indicator,
// not a data view -- the queue page itself surfaces per-feed errors).
export async function GET() {
  const auth = await requireAdminWithToken();
  if (!auth.ok) return auth.response;

  const [cd, mse] = await Promise.all([
    listCdTemplates(auth.token, { statusFilter: "pending_approval" }),
    listMseTemplates({ status: "pending_hitl" }),
  ]);

  const cdCount = cd.ok ? cd.data.length : 0;
  const mseCount = mse.ok ? mse.data.length : 0;

  return NextResponse.json({
    total: cdCount + mseCount,
    cloudDecoded: cdCount,
    mse: mseCount,
  });
}
