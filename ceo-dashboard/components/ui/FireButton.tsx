"use client";

import { useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { triggerAgent, pollIncident } from "@/lib/api";

type FireStatus = "idle" | "running" | "done" | "error";

interface FireButtonProps {
  agentId: string;
  label: string;
  payload: Record<string, unknown>;
}

const POLL_INTERVAL_MS = 3000;
const RESET_DELAY_MS = 8000;

export function FireButton({ agentId, label, payload }: FireButtonProps) {
  const [status, setStatus] = useState<FireStatus>("idle");
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const supabase = createClient();
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (pollTimer.current) clearInterval(pollTimer.current);
      if (resetTimer.current) clearTimeout(resetTimer.current);
    };
  }, []);

  function clearPoll() {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }

  function scheduleReset() {
    if (resetTimer.current) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => {
      if (!mounted.current) return;
      setStatus("idle");
      setIncidentId(null);
      setErrorMsg(null);
    }, RESET_DELAY_MS);
  }

  function fail(message: string) {
    clearPoll();
    if (!mounted.current) return;
    setStatus("error");
    setErrorMsg(message.slice(0, 50));
    scheduleReset();
  }

  async function handleClick() {
    if (status === "running") return;

    setStatus("running");
    setIncidentId(null);
    setErrorMsg(null);

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const authToken = session?.access_token;
      if (!authToken) {
        fail("Not signed in");
        return;
      }

      const result = await triggerAgent(agentId, payload, authToken);
      const currentIncidentId = result.runId;
      if (!mounted.current) return;
      setIncidentId(currentIncidentId);

      pollTimer.current = setInterval(async () => {
        try {
          const poll = await pollIncident(agentId, currentIncidentId, authToken);
          // Real vocabulary (core/hitl.py's execution_status, shared by the
          // commercial and internal-agent paths alike): pending_approval,
          // executing, executed, held, failed, budget_exceeded — there is no
          // "completed" value. Polling for that literal string never
          // matched, so a fire button looked stuck "Running…" forever even
          // on a successful run.
          if (poll.status === "executed") {
            clearPoll();
            if (!mounted.current) return;
            setStatus("done");
            scheduleReset();
          } else if (poll.status === "failed" || poll.status === "budget_exceeded") {
            fail(poll.error ?? "Agent run failed");
          }
          // pending_approval / executing / held: still running, keep polling.
        } catch (err) {
          fail(err instanceof Error ? err.message : "Poll failed");
        }
      }, POLL_INTERVAL_MS);
    } catch (err) {
      fail(err instanceof Error ? err.message : "Agent trigger failed");
    }
  }

  if (status === "running") {
    return (
      <button
        disabled
        className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold inline-flex items-center gap-1.5"
        style={{ border: "1px solid #e8963f", color: "#e8963f", backgroundColor: "transparent" }}
      >
        <span
          className="inline-block w-2.5 h-2.5 rounded-full animate-spin shrink-0"
          style={{ border: "2px solid #e8963f55", borderTopColor: "#e8963f" }}
        />
        Running…
      </button>
    );
  }

  if (status === "done") {
    return (
      <button
        disabled
        className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold"
        style={{ border: "1px solid #6fce8f", color: "#6fce8f", backgroundColor: "transparent" }}
      >
        ✓ {incidentId ? incidentId.slice(0, 8) : "done"}
      </button>
    );
  }

  if (status === "error") {
    return (
      <button
        onClick={handleClick}
        className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold"
        style={{ border: "1px solid #e05d5d", color: "#e05d5d", backgroundColor: "transparent" }}
        title={errorMsg ?? undefined}
      >
        ✕ {errorMsg}
      </button>
    );
  }

  return (
    <button
      onClick={handleClick}
      className="px-3 py-1.5 rounded-[6px] text-[11px] font-mono font-semibold transition-colors"
      style={{ border: "1px solid #3a4250", color: "#eef2f5", backgroundColor: "#10151b" }}
    >
      {label}
    </button>
  );
}
