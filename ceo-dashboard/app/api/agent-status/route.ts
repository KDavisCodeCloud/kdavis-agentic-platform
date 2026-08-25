import { NextRequest, NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { requireRole } from "@/lib/api-auth";
import type { VoiceAgentHealth } from "@/lib/types";

// Reads/writes jarvis-decoded's nova_agent_status table (migration 011) --
// the whole point of that table's design is that this dashboard and
// nova-voice.service never talk to each other directly, only through
// Supabase. nova_agent_status's RLS is service_role-only (same pattern as
// migration 010's nova_webhook_config), so this route -- not the
// anon-key client used elsewhere in this dashboard -- is the only way in.

const HEARTBEAT_STALE_MS = 30_000;

const AGENT_LABELS: Record<string, string> = {
  nova: "NOVA",
  apollo: "Apollo",
  ledger: "Ledger",
  counsel: "Counsel",
  board: "The Board",
};

function computeHealth(enabled: boolean, lastHeartbeatAt: string | null): VoiceAgentHealth {
  if (!enabled) return "off";
  if (!lastHeartbeatAt) return "unhealthy";
  return Date.now() - new Date(lastHeartbeatAt).getTime() < HEARTBEAT_STALE_MS ? "healthy" : "unhealthy";
}

export async function GET() {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const supabase = createAdminClient();
  const { data, error } = await supabase
    .from("nova_agent_status")
    .select("agent_slug, enabled, last_heartbeat_at, status_detail, updated_at, current_state, state_updated_at")
    .order("agent_slug", { ascending: true });

  if (error) {
    return NextResponse.json({ detail: error.message }, { status: 500 });
  }

  const agents = (data ?? []).map((row) => ({
    ...row,
    label: AGENT_LABELS[row.agent_slug] ?? row.agent_slug,
    health: computeHealth(row.enabled, row.last_heartbeat_at),
  }));

  return NextResponse.json({ agents });
}

export async function PATCH(request: NextRequest) {
  const auth = await requireRole(["admin"]);
  if (!auth.ok) return NextResponse.json({ detail: auth.error }, { status: auth.status });

  const body = await request.json().catch(() => null);
  const agentSlug = body?.agent_slug;
  const enabled = body?.enabled;

  if (typeof agentSlug !== "string" || typeof enabled !== "boolean") {
    return NextResponse.json(
      { detail: "agent_slug (string) and enabled (boolean) are required" },
      { status: 400 }
    );
  }

  const supabase = createAdminClient();
  const { error } = await supabase.from("nova_agent_status").update({ enabled }).eq("agent_slug", agentSlug);

  if (error) {
    return NextResponse.json({ detail: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
