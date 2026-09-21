import { NextResponse } from "next/server";
import { requireRole, getSupabaseAccessToken } from "@/lib/api-auth";
import type { BackendResult } from "./http";

// Shared guards for the app/api/email-campaigns/** route handlers. Neither
// backend has a "hitl" role today (see both docs/internal/email-approval-api.md
// files) and this app's own Role type has no "hitl" value either -- every
// email-campaigns route is admin-only until that changes on all three sides.
const ALLOWED_ROLES = ["admin"] as const;

export async function requireAdmin(): Promise<{ ok: true } | { ok: false; response: NextResponse }> {
  const auth = await requireRole([...ALLOWED_ROLES]);
  if (!auth.ok) return { ok: false, response: NextResponse.json({ detail: auth.error }, { status: auth.status }) };
  return { ok: true };
}

// Cloud Decoded routes additionally need the caller's own session token to
// forward (see lib/api-auth.ts's getSupabaseAccessToken doc comment).
export async function requireAdminWithToken(): Promise<{ ok: true; token: string } | { ok: false; response: NextResponse }> {
  const admin = await requireAdmin();
  if (!admin.ok) return admin;

  const token = await getSupabaseAccessToken();
  if (!token) {
    return { ok: false, response: NextResponse.json({ detail: "No active session token to forward" }, { status: 401 }) };
  }
  return { ok: true, token };
}

export function toResponse<T>(result: BackendResult<T>): NextResponse {
  if (!result.ok) return NextResponse.json({ detail: result.error }, { status: result.status });
  return NextResponse.json(result.data);
}
