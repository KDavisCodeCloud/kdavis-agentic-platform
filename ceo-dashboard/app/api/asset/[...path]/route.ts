import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Proxies to the Cloud Decoded FastAPI backend's live GET /api/v1/internal/
// marketing/assets/{path} (api/routes/internal_marketing.py's get_asset),
// same server-to-server pattern as app/api/linkedin-queue/generate/route.ts
// (session auth here via requireRole, then a X-API-Key/MARKETING_API_KEY
// call the backend trusts — never sent to the browser).
//
// Real bug fixed 2026-09-21: this route used to read a git-committed
// snapshot of assets_library/my_originals/ bundled into this app's own
// Vercel deployment at build time (see next.config.ts's git history for
// the removed outputFileTracingIncludes hack) -- a 2026-07-24 workaround
// from when the FastAPI backend "had never been deployed anywhere
// reachable." It has been live on Railway for weeks; nothing auto-commits
// a freshly generated PNG to git, so every image from a real run 404'd as
// "image failed to load" the moment MKT-LI1 started generating images at
// draft time again (surfaced in the review queue immediately, instead of
// only for approved/published rows nobody happened to check the
// thumbnail on). Proxying to the now-reachable backend serves the actual
// current file, live, regardless of when it was generated.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { detail: "MARKETING_API_KEY is not configured on this deployment" },
      { status: 500 }
    );
  }

  // pathSegments arrives as image_brief.image_path with only the leading
  // "assets_library/" stripped (see AssetThumbnail.tsx) — e.g.
  // "my_originals/cloud-and-ai-execution/foo.png". The backend's own
  // asset_path:path route param + _ASSETS_LIBRARY_ROOT resolve+
  // is_relative_to guard is the real traversal check; join with "/" here
  // (never using these segments as a filesystem path in this process).
  const { path: pathSegments } = await params;
  const assetPath = pathSegments.map(encodeURIComponent).join("/");

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/internal/marketing/assets/${assetPath}`, {
      headers: { "X-API-Key": apiKey },
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Could not reach the Cloud Decoded backend at ${API_BASE}: ${(err as Error).message}` },
      { status: 503 }
    );
  }

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    return NextResponse.json({ detail: detail.detail ?? `Fetching asset failed: ${res.status}` }, { status: res.status });
  }

  const bytes = await res.arrayBuffer();
  const contentType = res.headers.get("content-type") ?? "application/octet-stream";
  return new NextResponse(bytes, {
    headers: { "Content-Type": contentType, "Cache-Control": "private, max-age=3600" },
  });
}
