import { createClient } from "@supabase/supabase-js";

// Service-role client — bypasses RLS entirely. Server-only: SUPABASE_SERVICE_ROLE_KEY
// has no NEXT_PUBLIC_ prefix, so Next.js never bundles it into client-side code.
// Only ever import this from a Server Component or route handler, never from
// a "use client" component. Same pattern as ceo-dashboard/lib/supabase/admin.ts.
//
// Needed because opportunity_pipeline/mse_build_briefs RLS is
// app_metadata.role = 'admin' only (kdavis-microsaas-engine migration
// 20260716000009) — team members' role claim is never 'admin' by design
// (CLAUDE.md's Team Management System scopes them out of owner-level
// data), so the normal anon-key session client used elsewhere in this
// dashboard would just see zero rows. The build-queue page uses this to
// read the real data server-side, then hands the client only a
// deliberately curated subset (see app/build-queue/page.tsx) — never the
// raw MRR/verdict-reasoning fields CLAUDE.md keeps off the team's view.
export function createAdminClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { autoRefreshToken: false, persistSession: false } }
  );
}
