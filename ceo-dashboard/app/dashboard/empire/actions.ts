"use server";

import { revalidatePath } from "next/cache";

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_API_URL || "http://localhost:8001";

export async function resolveHitlTicket(id: string, resolution: string) {
  if (!resolution.trim()) {
    return { ok: false, error: "Resolution text is required." };
  }
  try {
    const res = await fetch(`${ORCHESTRATOR_URL}/hitl/${id}/resolve`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution, resolved_by: "kelvin" }),
      cache: "no-store",
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      return { ok: false, error: `Orchestrator returned ${res.status}: ${body}` };
    }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "Could not reach the Orchestrator." };
  }
  revalidatePath("/dashboard/empire");
  return { ok: true };
}
