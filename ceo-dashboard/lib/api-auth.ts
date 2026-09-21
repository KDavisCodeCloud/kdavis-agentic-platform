import { createClient } from "@/lib/supabase/server";
import { resolveRole } from "@/lib/role";
import type { Role } from "@/lib/types";

// Route handlers (app/api/**/route.ts) sit outside middleware.ts's
// DEPT_ROUTES role check (that only matches /dashboard/* paths), so each
// route using the service-role admin client must gate itself explicitly —
// otherwise any authenticated user, regardless of role, could call an
// RLS-bypassing endpoint directly. Mirrors the exact same role logic
// middleware.ts and app/dashboard/layout.tsx use (lib/role.ts), so this
// can never drift from what the sidebar/page-level checks already allow.
export async function requireRole(allowed: Role[]): Promise<{ ok: true } | { ok: false; status: number; error: string }> {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) return { ok: false, status: 401, error: "Not signed in" };

  const role = resolveRole(user.email, user.user_metadata?.role);
  if (!allowed.includes(role)) {
    return { ok: false, status: 403, error: `Role '${role}' is not permitted` };
  }

  return { ok: true };
}

// The Cloud Decoded Email Campaign feed's backend
// (api/middleware/internal_auth.py, kdavis-agentic-platform root) validates
// the signed-in admin's OWN Supabase session JWT directly -- ceo-dashboard
// and Cloud Decoded share the same Supabase project (see
// docs/internal/email-approval-api.md's Auth section), so its proxy routes
// forward this token as-is rather than using a static server-side API key.
// Call requireRole() first; this assumes a session already exists.
export async function getSupabaseAccessToken(): Promise<string | null> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}
