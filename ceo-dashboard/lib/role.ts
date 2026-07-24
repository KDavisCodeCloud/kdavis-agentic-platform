import type { Role } from "./types";

// Owner override lives here ONLY — found 2026-07-24: middleware.ts and
// app/dashboard/layout.tsx each reimplemented this resolution
// independently, and drifted apart. layout.tsx special-cased the owner
// email to "admin"; middleware.ts didn't, so it fell through to
// user_metadata.role ?? "rnd" for the owner too. The sidebar (driven by
// layout.tsx) correctly rendered admin-only links like Marketing as
// visible/clickable, but middleware then silently redirected any request
// to those routes back to /dashboard/overview, since "rnd" isn't in
// their allowed roles — clicking the link appeared to do nothing.
export const OWNER_EMAIL = "kdav2k5@gmail.com";

export function resolveRole(email: string | null | undefined, metadataRole: unknown): Role {
  if (email === OWNER_EMAIL) return "admin";
  return (typeof metadataRole === "string" ? metadataRole : "rnd") as Role;
}
