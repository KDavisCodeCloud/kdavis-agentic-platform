import { requireAdmin, toResponse } from "@/lib/email-campaigns/route-helpers";
import { getMseCampaignStatus } from "@/lib/email-campaigns/mse-client";

export async function GET() {
  const auth = await requireAdmin();
  if (!auth.ok) return auth.response;
  return toResponse(await getMseCampaignStatus());
}
