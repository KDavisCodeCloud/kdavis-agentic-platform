import { requireAdmin, toResponse } from "@/lib/email-campaigns/route-helpers";
import { approveMseTemplate } from "@/lib/email-campaigns/mse-client";

export async function POST(_request: Request, { params }: { params: Promise<{ key: string }> }) {
  const auth = await requireAdmin();
  if (!auth.ok) return auth.response;
  const { key } = await params;
  return toResponse(await approveMseTemplate(key));
}
