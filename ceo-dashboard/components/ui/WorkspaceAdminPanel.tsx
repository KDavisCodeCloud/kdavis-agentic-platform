"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  listWorkspaces,
  suspendWorkspace,
  reactivateWorkspace,
  rotateWorkspaceToken,
  type WorkspaceSummary,
} from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

// The actual revocation lever for Cloud Decoded's paywall (see
// api/routes/internal_workspaces.py): suspend for a ToS violation
// (independent of Stripe -- Stripe has no concept of a ToS violation),
// and rotate-token to cut off a leaked/compromised token immediately.
// Nothing here ever displays a workspace's existing token -- rotate-token
// is the only action that reveals one, and only the new one, once.

type RowAction = "suspend" | "reactivate" | "rotate" | null;

export function WorkspaceAdminPanel() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<RowAction>(null);
  const [revealedToken, setRevealedToken] = useState<{ workspaceId: string; token: string } | null>(null);

  const supabase = createClient();

  async function getAuthToken(): Promise<string> {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    const token = session?.access_token;
    if (!token) throw new Error("Not signed in");
    return token;
  }

  async function load() {
    setError(null);
    try {
      const token = await getAuthToken();
      const rows = await listWorkspaces(token);
      setWorkspaces(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workspaces");
    }
  }

  useEffect(() => {
    load();
  }, []);

  function updateRowStatus(id: string, status: string) {
    setWorkspaces((prev) => prev?.map((w) => (w.id === id ? { ...w, stripe_subscription_status: status } : w)) ?? null);
  }

  async function handleSuspend(w: WorkspaceSummary) {
    if (!confirm(`Suspend ${w.company_name}? This immediately blocks every protected endpoint (ToS violation path, independent of Stripe).`)) return;
    setPendingId(w.id);
    setPendingAction("suspend");
    setError(null);
    try {
      const token = await getAuthToken();
      const result = await suspendWorkspace(w.id, token);
      updateRowStatus(w.id, result.stripe_subscription_status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suspend failed");
    } finally {
      setPendingId(null);
      setPendingAction(null);
    }
  }

  async function handleReactivate(w: WorkspaceSummary) {
    if (!confirm(`Reactivate ${w.company_name}? This restores access immediately.`)) return;
    setPendingId(w.id);
    setPendingAction("reactivate");
    setError(null);
    try {
      const token = await getAuthToken();
      const result = await reactivateWorkspace(w.id, token);
      updateRowStatus(w.id, result.stripe_subscription_status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reactivate failed");
    } finally {
      setPendingId(null);
      setPendingAction(null);
    }
  }

  async function handleRotateToken(w: WorkspaceSummary) {
    if (!confirm(`Rotate the workspace token for ${w.company_name}? The current token stops working immediately -- the customer will need the new one to regain access.`)) return;
    setPendingId(w.id);
    setPendingAction("rotate");
    setError(null);
    setRevealedToken(null);
    try {
      const token = await getAuthToken();
      const result = await rotateWorkspaceToken(w.id, token);
      setRevealedToken({ workspaceId: w.id, token: result.workspace_token });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Token rotation failed");
    } finally {
      setPendingId(null);
      setPendingAction(null);
    }
  }

  if (error && !workspaces) {
    return (
      <p className="text-[12px]" style={{ color: "#e05d5d" }}>
        {error}
      </p>
    );
  }

  if (!workspaces) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        Loading workspaces…
      </p>
    );
  }

  if (workspaces.length === 0) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        No workspaces yet.
      </p>
    );
  }

  return (
    <div className="min-w-0">
      {error && (
        <p className="text-[11px] mb-3" style={{ color: "#e05d5d" }}>
          {error}
        </p>
      )}

      <div className="space-y-0">
        {workspaces.map((w) => {
          const isPending = pendingId === w.id;
          const canReactivate = w.stripe_subscription_status === "suspended" || w.stripe_subscription_status === "canceled";
          const revealed = revealedToken?.workspaceId === w.id ? revealedToken.token : null;

          return (
            <div key={w.id} className="py-3 min-w-0" style={{ borderTop: "1px solid #1c222b" }}>
              <div className="flex items-center justify-between gap-3 flex-wrap min-w-0">
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold truncate-text" style={{ color: "#eef2f5" }}>
                    {w.company_name}
                  </p>
                  <p className="text-[10.5px] font-mono" style={{ color: "#5b6673" }}>
                    {w.product_tier} · created {new Date(w.created_at).toLocaleDateString()}
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <StatusBadge status={w.stripe_subscription_status} />

                  {canReactivate ? (
                    <button
                      onClick={() => handleReactivate(w)}
                      disabled={isPending}
                      className="px-2.5 py-1 rounded-[6px] text-[10.5px] font-mono font-semibold disabled:opacity-50"
                      style={{ border: "1px solid #6fce8f", color: "#6fce8f", backgroundColor: "transparent" }}
                    >
                      {isPending && pendingAction === "reactivate" ? "Reactivating…" : "Reactivate"}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSuspend(w)}
                      disabled={isPending}
                      className="px-2.5 py-1 rounded-[6px] text-[10.5px] font-mono font-semibold disabled:opacity-50"
                      style={{ border: "1px solid #e05d5d", color: "#e05d5d", backgroundColor: "transparent" }}
                    >
                      {isPending && pendingAction === "suspend" ? "Suspending…" : "Suspend"}
                    </button>
                  )}

                  <button
                    onClick={() => handleRotateToken(w)}
                    disabled={isPending}
                    className="px-2.5 py-1 rounded-[6px] text-[10.5px] font-mono font-semibold disabled:opacity-50"
                    style={{ border: "1px solid #3a4250", color: "#eef2f5", backgroundColor: "#10151b" }}
                  >
                    {isPending && pendingAction === "rotate" ? "Rotating…" : "Rotate token"}
                  </button>
                </div>
              </div>

              {revealed && (
                <div
                  className="mt-2.5 flex items-center gap-2 rounded-[8px] px-3 py-2"
                  style={{ border: "1px solid #e8963f", backgroundColor: "#e8963f11" }}
                >
                  <code className="flex-1 truncate text-[11px] font-mono" style={{ color: "#f5a623" }}>
                    {revealed}
                  </code>
                  <button
                    onClick={() => navigator.clipboard.writeText(revealed)}
                    className="text-[10px] font-mono px-2 py-1 rounded-[5px] shrink-0"
                    style={{ border: "1px solid #3a4250", color: "#eef2f5" }}
                  >
                    Copy
                  </button>
                  <button
                    onClick={() => setRevealedToken(null)}
                    className="text-[10px] font-mono px-2 py-1 rounded-[5px] shrink-0"
                    style={{ border: "1px solid #3a4250", color: "#8b96a3" }}
                  >
                    Dismiss
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
