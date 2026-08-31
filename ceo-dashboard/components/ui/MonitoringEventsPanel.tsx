"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { MonitoringEventRow } from "./MonitoringEventRow";
import type { MonitoringEvent } from "@/lib/types";

interface MonitoringEventsPanelProps {
  /** Reports the current open-event count up to the parent, same shape as HITLQueuePanel's onCountChange. */
  onCountChange?: (count: number) => void;
}

export function MonitoringEventsPanel({ onCountChange }: MonitoringEventsPanelProps) {
  const supabase = createClient();
  const [items, setItems] = useState<MonitoringEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchOpen = useCallback(async () => {
    const { data } = await supabase
      .from("mse_monitoring_events")
      .select("*")
      .eq("status", "open")
      .order("created_at", { ascending: false });
    if (data) setItems(data as MonitoringEvent[]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchOpen();

    const channel = supabase
      .channel("monitoring_events_panel")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "mse_monitoring_events" },
        () => fetchOpen()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchOpen, supabase]);

  useEffect(() => {
    onCountChange?.(items.length);
  }, [items, onCountChange]);

  if (loading) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        Loading monitoring events…
      </p>
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        No open monitoring events.
      </p>
    );
  }

  return (
    <>
      {items.map((item) => (
        <MonitoringEventRow key={item.id} item={item} onResolved={fetchOpen} />
      ))}
    </>
  );
}
