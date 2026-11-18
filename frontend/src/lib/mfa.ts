// Cloud Decoded — TOTP enrollment against Supabase Auth, shared by the
// Members panel and the first-login MFA offer (app/login/page.tsx).

import { getSupabaseClient } from '@/lib/supabase'

export interface TotpEnrollment {
  factorId: string
  qrCode: string
  secret: string
}

export async function startTotpEnrollment(): Promise<TotpEnrollment> {
  const { data, error } = await getSupabaseClient().auth.mfa.enroll({ factorType: 'totp' })
  if (error || !data) throw new Error(error?.message || 'Could not start enrollment')
  return { factorId: data.id, qrCode: data.totp.qr_code, secret: data.totp.secret }
}

// Verifies the first code from the authenticator app; on success the factor
// is active and the session is upgraded to aal2. Returns the new access token.
export async function confirmTotpEnrollment(factorId: string, code: string): Promise<string> {
  if (code.trim().length !== 6) throw new Error('Enter the 6-digit code from your authenticator app')
  const supabase = getSupabaseClient()
  const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({ factorId })
  if (challengeError || !challenge) throw new Error(challengeError?.message || 'Could not verify code')
  const { data, error } = await supabase.auth.mfa.verify({ factorId, challengeId: challenge.id, code: code.trim() })
  if (error || !data) throw new Error(error?.message || 'Could not verify code')
  return data.access_token
}
