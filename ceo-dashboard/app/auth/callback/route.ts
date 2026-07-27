import { NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import type { EmailOtpType } from "@supabase/supabase-js";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const token_hash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const next = searchParams.get("next") ?? "/dashboard/overview";

  const cookieStore = await cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options?: Record<string, unknown> }[]) {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options as Parameters<typeof cookieStore.set>[2])
          );
        },
      },
    }
  );

  // Two different magic-link shapes need handling here, not just one:
  // - `code` (PKCE): only works if exchangeCodeForSession runs in the SAME
  //   browser that called signInWithOtp -- the code_verifier lives in a
  //   cookie set at request time. Opening the email link in a different
  //   app/browser (very common on phones -- Gmail app's in-app browser vs.
  //   whatever sent the original request) has no way to satisfy this and
  //   silently fails, which is exactly the "bounces back to login" symptom
  //   reported 2026-07-27 trying to get a second person signing in on mobile.
  // - `token_hash` + `type` (OTP verify): no browser-affinity requirement at
  //   all, works from any device/browser. Supabase's email template can be
  //   configured to send either shape; handling only `code` means any
  //   template using the token_hash link format -- or any cross-device
  //   click -- was guaranteed to fail before this fix.
  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  } else if (token_hash && type) {
    const { error } = await supabase.auth.verifyOtp({ type, token_hash });
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  return NextResponse.redirect(`${origin}/login?error=auth_failed`);
}
