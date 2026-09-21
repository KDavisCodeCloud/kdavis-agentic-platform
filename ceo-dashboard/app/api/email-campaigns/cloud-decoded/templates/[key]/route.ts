import { NextRequest } from "next/server";
import { requireAdminWithToken, toResponse } from "@/lib/email-campaigns/route-helpers";
import { getCdTemplate, updateCdTemplate } from "@/lib/email-campaigns/cloud-decoded-client";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const auth = await requireAdminWithToken();
  if (!auth.ok) return auth.response;
  const { key } = await params;
  return toResponse(await getCdTemplate(auth.token, key));
}

export async function PUT(request: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const auth = await requireAdminWithToken();
  if (!auth.ok) return auth.response;
  const { key } = await params;
  const body = await request.json().catch(() => ({}));
  return toResponse(await updateCdTemplate(auth.token, key, body));
}
