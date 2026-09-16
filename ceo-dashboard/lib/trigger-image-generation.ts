// Calls the Cloud Decoded FastAPI backend's POST /api/v1/internal/marketing/
// linkedin-queue/generate-images (api/routes/internal_marketing.py) --
// the bridge that makes image-generation-on-approval actually run in
// production. Found 2026-09-16: app/api/linkedin-queue/[id]/route.ts and
// .../batch-approve/route.ts write straight to Supabase and never call that
// backend's own PATCH/batch-approve endpoints, so the backend has no way to
// observe a row becoming 'approved' unless a caller tells it explicitly.
//
// Same server-to-server pattern as app/api/linkedin-queue/generate/route.ts
// (X-API-Key = MARKETING_API_KEY, NEXT_PUBLIC_API_URL) -- but that route's
// dependency is get_internal_user (browser JWT) shaped for the browser;
// this backend endpoint is gated by require_marketing_api_key instead,
// same as linkedin-on-demand, since this call has no Supabase session JWT
// to present.
//
// Never throws -- a slow or unreachable backend must never fail or block
// the caller's own (already-succeeded) Supabase write. Errors are logged
// server-side only; the dashboard shows the row as approved regardless,
// and a missing image is still visible/recoverable in the review UI.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function triggerImageGeneration(queueIds: string[]): Promise<void> {
  if (queueIds.length === 0) return;

  const apiKey = process.env.MARKETING_API_KEY;
  if (!apiKey) {
    console.error("[trigger-image-generation] MARKETING_API_KEY is not configured on this deployment — skipping");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/v1/internal/marketing/linkedin-queue/generate-images`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify({ queue_ids: queueIds }),
      cache: "no-store",
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      console.error(`[trigger-image-generation] Backend returned ${res.status}:`, detail);
    }
  } catch (err) {
    console.error(`[trigger-image-generation] Could not reach the Cloud Decoded backend at ${API_BASE}:`, err);
  }
}
