// Shared low-level fetch wrapper for the two Email Campaign backend
// clients (cloud-decoded-client.ts, mse-client.ts). Both feeds need the
// same "never throw, always return a typed result" shape so a proxy route
// can turn a network failure into a per-feed 503 instead of a 500 or an
// unhandled rejection -- see the plan's "degrades to a descriptive 503
// per-feed, never blanks the page" requirement.
export type BackendResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: string };

export async function backendFetch<T>(
  url: string,
  init: RequestInit,
  backendLabel: string
): Promise<BackendResult<T>> {
  let res: Response;
  try {
    res = await fetch(url, { ...init, cache: "no-store" });
  } catch (err) {
    return {
      ok: false,
      status: 503,
      error: `Could not reach the ${backendLabel} backend at ${url}: ${(err as Error).message}`,
    };
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      error: (data as { detail?: string }).detail ?? `${backendLabel} request failed: ${res.status}`,
    };
  }
  return { ok: true, data: data as T };
}
