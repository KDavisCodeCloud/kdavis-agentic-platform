import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { requireRole } from "@/lib/api-auth";

// Serves assets_library/my_originals/ images (Gemini-generated LinkedIn
// diagrams) directly from this deployment — see next.config.ts's
// outputFileTracingIncludes, which bundles that folder (5.8MB) into this
// route's serverless function. Only my_originals/ is bundled/served here;
// other asset_library categories (ai_agents/, cloud_devops/, etc., used
// for non-Gemini-generated posts) are out of scope for now since nothing
// in the live batch currently references them.
//
// Gated the same way as every other route touching this data
// (lib/api-auth.ts) — these are pre-publish drafts, not meant to be
// openly fetchable even though the content is low-sensitivity.
const ASSETS_LIBRARY_ROOT = path.resolve(process.cwd(), "..", "assets_library");
const MY_ORIGINALS_ROOT = path.resolve(ASSETS_LIBRARY_ROOT, "my_originals");

const MIME_TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
};

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const auth = await requireRole(["admin", "marketing"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  // pathSegments arrives as image_brief.image_path with only the leading
  // "assets_library/" stripped (see AssetThumbnail.tsx) — i.e. it starts
  // with "my_originals/...", matching ASSETS_LIBRARY_ROOT as the base.
  const { path: pathSegments } = await params;
  const requested = path.resolve(ASSETS_LIBRARY_ROOT, ...pathSegments);

  // Path traversal guard, and scoped to my_originals/ specifically (the
  // only category actually bundled — see next.config.ts).
  if (!requested.startsWith(MY_ORIGINALS_ROOT)) {
    return NextResponse.json({ detail: "Invalid asset path" }, { status: 400 });
  }

  const ext = path.extname(requested).toLowerCase();
  const mimeType = MIME_TYPES[ext];
  if (!mimeType) {
    return NextResponse.json({ detail: "Unsupported file type" }, { status: 400 });
  }

  try {
    const bytes = await readFile(requested);
    return new NextResponse(new Uint8Array(bytes), {
      headers: { "Content-Type": mimeType, "Cache-Control": "private, max-age=3600" },
    });
  } catch {
    return NextResponse.json({ detail: "Asset not found" }, { status: 404 });
  }
}
