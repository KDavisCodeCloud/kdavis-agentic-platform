import { NextRequest } from "next/server";
import { requireAdmin, toResponse } from "@/lib/email-campaigns/route-helpers";
import { listMseTemplates } from "@/lib/email-campaigns/mse-client";

export async function GET(request: NextRequest) {
  const auth = await requireAdmin();
  if (!auth.ok) return auth.response;

  const result = await listMseTemplates({
    status: request.nextUrl.searchParams.get("status") ?? undefined,
    productId: request.nextUrl.searchParams.get("product_id") ?? undefined,
  });
  return toResponse(result);
}
