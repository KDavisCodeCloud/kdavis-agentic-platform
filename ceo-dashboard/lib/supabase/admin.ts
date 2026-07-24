import { createClient } from "@supabase/supabase-js";

// Service-role client — bypasses RLS entirely. Server-only: SUPABASE_SERVICE_ROLE_KEY
// has no NEXT_PUBLIC_ prefix, so Next.js never bundles it into client-side code.
// Only ever import this from route handlers (app/api/**/route.ts) or other
// server-only code — never from a "use client" component.
//
// Needed because linkedin_content_queue's RLS policy is "FOR ALL TO service_role"
// only (db/migrations/007_marketing_queues.sql) — the anon-key session client
// used everywhere else in this dashboard (lib/supabase/client.ts, server.ts)
// cannot read or write it at all.
export function createAdminClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { autoRefreshToken: false, persistSession: false } }
  );
}
