const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function triggerAgent(
  agentId: string,
  payload: Record<string, unknown>,
  authToken: string,
): Promise<{ incident_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/agents/${agentId}/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({ payload }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Agent trigger failed: ${res.status}`);
  }
  return res.json();
}

export async function pollIncident(
  incidentId: string,
  authToken: string,
): Promise<{ status: string; output?: unknown }> {
  const res = await fetch(`${API_BASE}/incidents/${incidentId}`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`);
  return res.json();
}
