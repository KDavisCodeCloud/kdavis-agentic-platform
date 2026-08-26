"use client";

import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: {
        // Default flowType is 'pkce': the magic-link email carries a `code`
        // that can only be exchanged in the exact browser/storage context
        // that called signInWithOtp(). Clicking the link anywhere else
        // (system default browser instead of the NOVA desktop app, or a
        // different device/app on mobile -- the same class of bug already
        // hit and partially handled in app/auth/callback/route.ts's
        // token_hash branch) fails with no way to recover. 'implicit'
        // makes Supabase email a token_hash+type link instead, which that
        // route already verifies with no browser affinity requirement --
        // the actual fix, not a workaround, for a single-operator internal
        // tool where email-allowlisted role access (see middleware.ts's
        // resolveRole) already gates who can sign in at all.
        flowType: "implicit",
      },
    }
  );
}
