import { NextRequest } from "next/server";
import { requireAdminWithToken, toResponse } from "@/lib/email-campaigns/route-helpers";
import { listCdTemplates } from "@/lib/email-campaigns/cloud-decoded-client";

export async function GET(request: NextRequest) {
  const auth = await requireAdminWithToken();
  if (!auth.ok) return auth.response;

  const result = await listCdTemplates(auth.token, {
    statusFilter: request.nextUrl.searchParams.get("status_filter") ?? undefined,
    sequenceKey: request.nextUrl.searchParams.get("sequence_key") ?? undefined,
  });
  return toResponse(result);
}
