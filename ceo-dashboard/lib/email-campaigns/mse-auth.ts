import jwt from "jsonwebtoken";

// Mints a short-lived admin-role JWT for calling mse-api's
// /marketing/internal/* routes (api/routers/marketing_internal.py in
// kdavis-microsaas-engine), which are admin-JWT-gated rather than
// MARKETING_API_KEY shared-secret-gated (see that router's own module
// docstring for why: per-actor attribution on approvals).
//
// This does NOT mint a new credential -- MSE_SUPABASE_JWT_SECRET is a
// copy of the SAME SUPABASE_JWT_SECRET value already provisioned on the
// mse-api Railway service. mse-api's auth middleware
// (api/middleware/auth.py verify_jwt / api/middleware/tenant_context.py)
// verifies HS256 tokens against that secret with no database lookup --
// it trusts any token bearing app_metadata.role="admin", the same way
// the codebase's own "synthetic test tokens" already do (see verify_jwt's
// comment). Signing our own token here is the intended mechanism for a
// trusted first-party server (ceo-dashboard's Next.js server, never the
// browser) to act as admin, not a workaround.
export function signMseAdminJwt(): string | null {
  const secret = process.env.MSE_SUPABASE_JWT_SECRET;
  if (!secret) return null;
  return jwt.sign(
    {
      sub: "ceo-dashboard-service",
      aud: "authenticated",
      role: "authenticated",
      app_metadata: { role: "admin" },
    },
    secret,
    { algorithm: "HS256", expiresIn: "5m" }
  );
}
