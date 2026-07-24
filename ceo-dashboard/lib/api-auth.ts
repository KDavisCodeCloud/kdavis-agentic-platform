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
