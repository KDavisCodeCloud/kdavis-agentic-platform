import { NextRequest } from "next/server";
import { requireAdminWithToken, toResponse } from "@/lib/email-campaigns/route-helpers";
import { getCdMetrics } from "@/lib/email-campaigns/cloud-decoded-client";

export async function GET(request: NextRequest) {
  const auth = await requireAdminWithToken();
  if (!auth.ok) return auth.response;
  return toResponse(await getCdMetrics(auth.token, request.nextUrl.searchParams.get("sequence_key") ?? undefined));
}
