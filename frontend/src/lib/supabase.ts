// Cloud Decoded — Supabase Auth client (membership plan, Phase A)
//
// This is the human-member login path, additive to the existing raw
// workspace-token flow (see app/login/page.tsx and lib/api.ts's
// isMemberSessionToken()). Uses the anon key + client-side SDK exactly
// as Supabase Auth is designed for -- session tokens issued here are
// validated server-side by api/middleware/auth.py's get_workspace_member
// via an online client.auth.get_user() call, not trusted blindly.

import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

let _client: SupabaseClient | null = null

// Lazy singleton, not a module-level createClient() call -- avoids
// throwing at import time in any environment (tests, a build step)
// where the env vars aren't set, since most of this app's existing
// pages don't need Supabase Auth at all (workspace-token login still
// works with zero Supabase config).
export function getSupabaseClient(): SupabaseClient {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    throw new Error(
      'NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY are not configured -- ' +
      'member login is unavailable until these are set.'
    )
  }
  if (!_client) {
    _client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  }
  return _client
}

export function isSupabaseConfigured(): boolean {
  return !!SUPABASE_URL && !!SUPABASE_ANON_KEY
}
