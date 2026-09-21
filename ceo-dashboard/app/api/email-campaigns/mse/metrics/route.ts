import { NextRequest } from "next/server";
import { requireAdmin, toResponse } from "@/lib/email-campaigns/route-helpers";
import { getMseMetrics } from "@/lib/email-campaigns/mse-client";

export async function GET(request: NextRequest) {
  const auth = await requireAdmin();
  if (!auth.ok) return auth.response;
  return toResponse(await getMseMetrics(request.nextUrl.searchParams.get("product_id") ?? undefined));
}
