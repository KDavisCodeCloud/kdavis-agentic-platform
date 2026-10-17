"use client";

// The Loop Map's sections outside the office floor: the waiting strip, the
// Holes Log, and the reference sections (90 days / this week / playbooks).
// Markup and copy follow docs/design/loop-map-reference.html; the waiting strip
// and the counts in "this week's moves" are computed from live data instead of
// the reference's hand-written snapshot.

import type { LoopMapData, Product } from "./model";
import { fmt, waitingCards } from "./model";

export function WaitingStrip({ products }: { products: Product[] }) {
  const cards = waitingCards(products);
  if (!cards.length) return null;
  return (
    <section className="waiting" aria-label="Where every loop is waiting">
      {cards.map((c) => (
        <div key={c.slug} className={`wait s-${c.cls}`}>
          <b>{c.title}</b>
          <p>{c.body}</p>
        </div>
      ))}
    </section>
  );
}

export function HolesLog({ products, showAll, setShowAll, onResolve }: {
  products: Product[];
  showAll: boolean;
  setShowAll: (v: boolean) => void;
  onResolve: (id: string, resolved: boolean) => void;
}) {
  const rows = products
    .flatMap((p) => p.notes.map((n) => ({ n, p, step: p.stations.find((s) => s.step_order === n.step_order) })))
    .filter(({ n }) => showAll || (n.kind === "hole" && !n.resolved_at))
    .sort((a, b) => b.n.created_at.localeCompare(a.n.created_at));
  return (
    <section className="card" id="holes">
      <div className="row">
        <h2>HOLES LOG · ALL PRODUCTS</h2>
        <label className="hole">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show resolved and general notes
        </label>
      </div>
      <p className="hint">Every note you log lands here with its product, step and date. Open holes are what&apos;s slowing a loop down. Resolve one when it&apos;s fixed; it stays on record.</p>
      <div className="tblwrap">
        <table className="tbl">
          <thead><tr><th>Logged</th><th>Product</th><th>Step</th><th>Note</th><th>Status</th></tr></thead>
          <tbody>
            {rows.length ? rows.map(({ n, p, step }) => (
              <tr key={n.id}>
                <td className="mono">{fmt(n.created_at)}</td>
                <td>{p.name}</td>
                <td>{n.step_order}. {step?.name ?? ""}</td>
                <td className="txt">{n.text}</td>
                <td>{n.kind === "hole"
                  ? <button className="linkbtn" onClick={() => onResolve(n.id, !n.resolved_at)}>{n.resolved_at ? "Resolved · reopen" : "Open · mark resolved"}</button>
                  : "Note"}</td>
              </tr>
            )) : (
              <tr><td colSpan={5} className="empty">{showAll ? "Nothing logged yet." : "No open holes. Log one from any step when something is missing or broken."}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ReferenceSections({ counters }: { counters: LoopMapData["counters"] | null }) {
  const approve = counters?.awaiting_approval;
  const buyers = counters?.awaiting_buyer;
  return (
    <>
      <section className="cols">
        <div className="card">
          <h2>NEXT 90 DAYS, REALISTICALLY</h2>
          <div className="tblwrap"><table className="tbl">
            <thead><tr><th>Product</th><th>If you run the daily block</th><th>Worth</th></tr></thead>
            <tbody>
              <tr><td>Consulting</td><td>3–4 calls, ~1 engagement</td><td className="mono">$5–15K</td></tr>
              <tr><td>Cloud Decoded</td><td>2–3 demos, 0–1 customer</td><td className="mono">$299–699/mo</td></tr>
              <tr><td>Small Portfolio Hub</td><td>1–3 customers</td><td className="mono">$99–199/mo ea</td></tr>
              <tr><td>DecodedSix</td><td>Launch-window traffic</td><td className="mono">$200–3K/mo</td></tr>
              <tr><td>ADA Title II · Bible apps</td><td>Not built yet</td><td className="mono">—</td></tr>
            </tbody>
          </table></div>
          <p className="muted" style={{ fontSize: 13 }}>Cold email averages about a 3.4% reply rate in 2026 and well under 1 meeting per 100 sends. These ranges assume your hiring-signal targeting does a bit better than average.</p>
        </div>
        <div className="card">
          <h2>THIS WEEK&apos;S MOVES, IN ORDER</h2>
          <ol className="moves">
            <li><b>Approve the {approve ?? "waiting"} waiting draft{approve === 1 ? "" : "s"}</b> in CEO Decoded → Marketing → Outreach.</li>
            <li><b>5 buyer lookups a day</b> in Find the Buyer. {buyers ?? "Some"} compan{buyers === 1 ? "y is" : "ies are"} waiting for a name.</li>
            <li><b>Add the DMARC record</b> in Namecheap and click the green check on the row.</li>
            <li><b>Write a one-page consulting offer with a price.</b></li>
            <li><b>2 landlord-group posts for SPH</b> (Wednesday block).</li>
            <li><b>Pick the 10 launch-day DecodedSix articles</b> and confirm the map can go live Nov 19.</li>
          </ol>
        </div>
      </section>

      <section className="card">
        <h2>WHICH PLAYBOOK FITS A NEW PRODUCT</h2>
        <div className="tblwrap"><table className="tbl">
          <thead><tr><th>Buyer</th><th>Loop</th><th>Your products</th></tr></thead>
          <tbody>
            <tr><td>Company with a visible need (hiring, deadline)</td><td>Signal outbound: find signal → name buyer → approve → send → call</td><td>Consulting, Cloud Decoded, ADA Title II</td></tr>
            <tr><td>Small business owner who buys on their own</td><td>Community + search: helpful posts where they gather → site → self-serve checkout</td><td>Small Portfolio Hub, TradesDesk</td></tr>
            <tr><td>Audience you monetize</td><td>Content: timely articles → search → ads + affiliate</td><td>DecodedSix</td></tr>
            <tr><td>Consumers reached through a leader</td><td>Distributor: one pastor says yes → whole group joins → app store</td><td>Bible devotional apps</td></tr>
          </tbody>
        </table></div>
      </section>

      <footer><p>Your check marks, laps and notes are saved in CEO Decoded, so they&apos;re there on any device. Desk colors are recomputed from production every time this page refreshes, and snapshotted hourly for the 4-week strips.</p></footer>
    </>
  );
}
