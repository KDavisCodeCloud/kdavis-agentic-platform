"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { HitlApprovalRow } from "./HitlApprovalRow";
import type { HitlItem } from "@/lib/types";

interface HITLQueuePanelProps {
  /** Reports the current pending-item count up to the parent (Overview's "Open HITL Items" metric card). */
  onCountChange?: (count: number) => void;
}

export function HITLQueuePanel({ onCountChange }: HITLQueuePanelProps) {
  const supabase = createClient();
  const [items, setItems] = useState<HitlItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPending = useCallback(async () => {
    const { data } = await supabase
      .from("hitl_queue")
      .select("*")
      .eq("status", "pending")
      .order("created_at", { ascending: false });
    if (data) setItems(data as HitlItem[]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchPending();

    const channel = supabase
      .channel("hitl_queue_panel")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "hitl_queue" },
        () => fetchPending()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchPending, supabase]);

  useEffect(() => {
    onCountChange?.(items.length);
  }, [items, onCountChange]);

  if (loading) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        Loading queue…
      </p>
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-[11px] font-mono" style={{ color: "#5b6673" }}>
        No items pending approval
      </p>
    );
  }

  return (
    <>
      {items.map((item) => (
        <HitlApprovalRow key={item.id} item={item} onResolved={fetchPending} />
      ))}
    </>
  );
}
