// Loop Map -- data shapes from GET /marketing/loop-map (kdavis-microsaas-engine
// api/routers/loop_map.py) and the pure helpers the component renders with.
// The sprite grid and palette are the reference design's own (SPR / PAL in
// docs/design/loop-map-reference.html), copied unchanged.

export type Status = "working" | "not_proven" | "waiting_on_you" | "blocked" | "not_built" | "unknown";

export interface HistoryCell { day: string; status: Status | null }

export interface Station {
  step_order: number;
  name: string;
  owner: "auto" | "you";
  description: string | null;
  next_action: string | null;
  lane_link: string | null;
  target_hint: string | null;
  rule_key: string;
  status: Status;
  count: number | null;
  evidence: string;
  evidence_at: string | null;
  evidence_link: string | null;
  status_since: string | null;
  history: HistoryCell[];
  done: boolean;
  done_at: string | null;
}

export interface Note {
  id: string;
  product_id: string;
  step_order: number;
  lap: number;
  kind: "hole" | "note";
  text: string;
  created_at: string;
  created_by: string | null;
  resolved_at: string | null;
}

export interface Chip { text: string; live: boolean; status?: Status; tone?: string; evidence?: string }

export interface FunnelWeek {
  week: string; qualified: number; approved: number; sent: number; replies: number; calls: number; won: number;
}

export interface Product {
  product_id: string;
  slug: string;
  name: string;
  playbook: string;
  playbook_line: string | null;
  verdict: { tone: string | null; title: string | null; body: string | null };
  math: [string, string][];
  chips: Chip[];
  lap: number;
  laps_finished: number;
  last_lap_at: string | null;
  stations: Station[];
  notes: Note[];
  funnel: FunnelWeek[] | null;
}

export interface LoopMapData {
  generated_at: string;
  products: Product[];
  counters: { awaiting_buyer: number; awaiting_approval: number; ready_to_paste: number };
}

// status -> the reference's color class (s-ok/s-warn/...); unknown is the one
// status the reference never had, and gets its own token so it can never be
// mistaken for green.
export const CLS: Record<Status, string> = {
  working: "ok", not_proven: "warn", waiting_on_you: "you", blocked: "stop", not_built: "none", unknown: "unk",
};

export const LAB: Record<Status, string> = {
  working: "WORKING", not_proven: "NOT PROVEN", waiting_on_you: "YOUR MOVE", blocked: "BLOCKED",
  not_built: "NOT BUILT", unknown: "UNKNOWN",
};

export const SPR = ["..XXXX..", ".XSSSSX.", ".XSESEX.", ".XSSSSX.", "..BBBB..", ".BBBBBB.", "SBBBBBBS", "..BBBB..", "..L..L..", ".LL..LL."];
export const PAL: Record<string, string> = { X: "#2b1d14", S: "#c58b5f", E: "#0f1420", B: "#7aa2ff", L: "#3a4566" };

export function spriteRects(): { x: number; y: number; fill: string }[] {
  const out: { x: number; y: number; fill: string }[] = [];
  SPR.forEach((row, y) => [...row].forEach((c, x) => { if (PAL[c]) out.push({ x: x * 4, y: y * 4, fill: PAL[c] }); }));
  return out;
}

export const fmt = (t: string | number | null | undefined) =>
  t == null ? "" : new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function daysSince(iso: string | null, now = Date.now()): number | null {
  if (!iso) return null;
  return Math.floor((now - new Date(iso).getTime()) / 86_400_000);
}

/** Index of the desk the worker stands at: the first unchecked one, or the flag. */
export function target(p: Product): number {
  const i = p.stations.findIndex((s) => !s.done);
  return i < 0 ? p.stations.length : i;
}

export function openHoles(p: Product, step?: number): number {
  return p.notes.filter((n) => n.kind === "hole" && !n.resolved_at && (step == null || n.step_order === step)).length;
}

export interface WaitCard { slug: string; cls: string; title: string; body: string }

/** "Where every loop is waiting": per product, the first desk (in loop order)
 *  that is blocked or waiting on Kelvin -- the point the loop stops today. */
export function waitingCards(products: Product[]): WaitCard[] {
  const cards: WaitCard[] = [];
  for (const p of products) {
    const s = p.stations.find((x) => x.status === "blocked" || x.status === "waiting_on_you");
    if (!s) continue;
    const blocked = s.status === "blocked";
    const days = daysSince(s.status_since);
    cards.push({
      slug: p.slug,
      cls: CLS[s.status],
      title: `${p.name.toUpperCase()} ${blocked ? "IS BLOCKED AT" : "WAITS ON YOU AT"} ${s.name.toUpperCase()}`,
      body: s.evidence + (days != null && days >= 1 ? ` Same status for ${days} day${days === 1 ? "" : "s"}.` : ""),
    });
  }
  return cards;
}

/** Dashboard href for a station's lane, e.g. "/marketing#outreach". */
export function laneHref(link: string | null): string | null {
  if (!link) return null;
  return link.startsWith("http") ? link : `/dashboard${link.startsWith("/") ? "" : "/"}${link}`;
}
