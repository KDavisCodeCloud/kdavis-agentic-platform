import { requireAdminWithToken, toResponse } from "@/lib/email-campaigns/route-helpers";
import { deactivateCdSequence } from "@/lib/email-campaigns/cloud-decoded-client";

export async function POST(_request: Request, { params }: { params: Promise<{ key: string }> }) {
  const auth = await requireAdminWithToken();
  if (!auth.ok) return auth.response;
  const { key } = await params;
  return toResponse(await deactivateCdSequence(auth.token, key));
}
