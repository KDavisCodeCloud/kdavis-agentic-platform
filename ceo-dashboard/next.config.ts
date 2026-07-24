import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    typedRoutes: true,
  },
  // Forces Vercel to bundle assets_library/my_originals/ (repo root, one
  // level above this app's own directory) into this one route's
  // serverless function. Only 5.8MB total as of 2026-07-24 -- small
  // enough to bundle directly rather than a separate image host/backend.
  // Without this, files outside ceo-dashboard/ are traced out of the
  // deployment entirely and the route 404s at runtime even though it
  // works in local dev (where the full repo is on disk regardless).
  //
  // Key must be "/api/asset/**", not the literal route path
  // "/api/asset/[...path]" -- Next.js matches these keys with picomatch,
  // which parses "[...path]" as a glob character class (bracket syntax),
  // not literal text, so the exact route path never matches. Confirmed
  // by reading node_modules/next/dist/build/collect-build-traces.js
  // directly after the exact-path version silently traced 0 files.
  outputFileTracingIncludes: {
    "/api/asset/**": ["../assets_library/my_originals/**/*"],
  },
};

export default nextConfig;
