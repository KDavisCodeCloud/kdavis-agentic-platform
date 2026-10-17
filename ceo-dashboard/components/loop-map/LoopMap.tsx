"use client";
// REFACTOR CANDIDATE -- the office floor (tabs, desks, walker, step card) in
// one component because the walker animation needs all of it in one place.

// The Loop Map tab. A port of docs/design/loop-map-reference.html into React:
// same markup, classes, sprite, walk timing and two-click confirms. What
// changed is where the data comes from -- desk colors are live system status
// from GET /marketing/loop-map, and check marks / laps / notes are rows in
// mse_loop_* written through /api/loop-map (admin only).
//
// Desk color (system status) and the check mark (Kelvin's completion) are
// separate fields from separate tables; nothing here writes one from the other.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import "./loop-map.css";
import type { LoopMapData, Product, Station } from "./model";
import { CLS, LAB, daysSince, fmt, laneHref, openHoles, spriteRects, target } from "./model";
import { HolesLog, ReferenceSections, WaitingStrip } from "./LoopMapSections";

const REFRESH_MS = 60_000;
const STEP_MS = 620;
const LAP_PAUSE_MS = 1400;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const reduce = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

async function api(path: string, body?: unknown) {
  const res = await fetch(`/api/loop-map${path}`, {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof json?.detail === "string" ? json.detail : `HTTP ${res.status}`);
  return json;
}

function Sprite() {
  return (
    <svg viewBox="0 0 32 40" width="32" height="40" aria-hidden="true">
      {spriteRects().map((r, i) => <rect key={i} x={r.x} y={r.y} width="4" height="4" fill={r.fill} />)}
    </svg>
  );
}

function Desk({ s, i, sel, p, onSelect }: { s: Station; i: number; sel: number; p: Product; onSelect: (i: number) => void }) {
  const holes = openHoles(p, s.step_order);
  const notes = p.notes.filter((n) => n.step_order === s.step_order).length;
  const cls = CLS[s.status];
  return (
    <div className="slot" data-slot={i}>
      <button className={`desk s-${cls}${s.done ? " done" : ""}`} aria-pressed={i === sel} onClick={() => onSelect(i)}>
        <span className="num">{String(i + 1).padStart(2, "0")}</span>
        <span className="who">{s.owner === "you" ? "YOU" : "AUTO"}</span>
        <span className="name">{s.name}</span>
        <span className="stat">{s.evidence}</span>
        <span className="lab">{LAB[s.status]}</span>
        <span className={`badge${holes ? " hb" : notes ? " nb" : ""}`}>
          {holes ? `${holes} HOLE${holes > 1 ? "S" : ""}` : notes ? `${notes} NOTE${notes > 1 ? "S" : ""}` : ""}
        </span>
      </button>
      <div className="hist" role="img" aria-label={`${s.name}: last 4 weeks of status, one cell per day`}>
        {s.history.map((h) => (
          <i key={h.day} className={h.status ? `s-${CLS[h.status]}` : "empty"} title={`${h.day}: ${h.status ? LAB[h.status] : "no snapshot"}`} />
        ))}
      </div>
      <div className="histcap"><span>4 WK</span><span>TODAY</span></div>
    </div>
  );
}

export function LoopMap() {
  const [data, setData] = useState<LoopMapData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const [armed, setArmed] = useState<null | "lap" | "reset">(null);
  const [isWalking, setIsWalking] = useState(false);
  const [bubble, setBubble] = useState("");
  const [draft, setDraft] = useState("");
  const [isHole, setIsHole] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const walking = useRef(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const walkerRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const d: LoopMapData = await api("");
      // A 200 that isn't the map (an auth redirect page, a proxy error body)
      // must show as an error, not crash the tab.
      if (!d || !Array.isArray(d.products)) throw new Error("The Loop Map API returned an unexpected response");
      setData(d);
      setErr(null);
      return d;
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the Loop Map");
      return null;
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => { if (!walking.current) void load(); }, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const products = data?.products ?? [];
  const cur = products.find((p) => p.slug === slug) ?? products[0] ?? null;

  // First tab: #hash, then the remembered tab, then the first product.
  useEffect(() => {
    if (!data || slug) return;
    let start = data.products[0]?.slug ?? null;
    const h = window.location.hash.slice(1);
    let saved: string | null = null;
    try { saved = window.localStorage.getItem("loopTab"); } catch { /* storage unavailable */ }
    if (data.products.some((p) => p.slug === h)) start = h;
    else if (saved && data.products.some((p) => p.slug === saved)) start = saved;
    show(start, data.products);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  function show(id: string | null, list = products) {
    const p = list.find((x) => x.slug === id) ?? list[0];
    if (!p) return;
    setSlug(p.slug);
    setArmed(null);
    try { window.localStorage.setItem("loopTab", p.slug); } catch { /* storage unavailable */ }
    const first = p.stations.findIndex((s) => !s.done);
    setSel(Math.min(first < 0 ? 0 : first, p.stations.length - 1));
  }

  // ---- walker -------------------------------------------------------------
  const slotXY = useCallback((i: number) => {
    const el = trackRef.current?.querySelector<HTMLElement>(`[data-slot="${i}"]`);
    if (!el) return { x: 0, y: 0 };
    return { x: el.offsetLeft + el.offsetWidth / 2 - 16, y: el.offsetTop + 4 };
  }, []);

  const place = useCallback((p: Product, i: number, anim: boolean) => {
    const w = walkerRef.current;
    if (!w) return;
    const { x, y } = slotXY(i);
    w.style.transition = anim ? "" : "none";
    w.style.transform = `translate(${x}px,${y}px)`;
    if (!anim) { void w.offsetWidth; w.style.transition = ""; }
    setBubble(i >= p.stations.length ? "LAP COMPLETE!" : p.stations[i].owner === "you" ? "YOUR MOVE" : "WORKING ON IT");
  }, [slotXY]);

  const walkTo = useCallback(async (p: Product, from: number, to: number) => {
    walking.current = true;
    setIsWalking(true);
    setBubble("");
    for (let i = from + 1; i <= to; i++) {
      const { x, y } = slotXY(i);
      if (walkerRef.current) walkerRef.current.style.transform = `translate(${x}px,${y}px)`;
      await sleep(reduce() ? 0 : STEP_MS);
    }
    setIsWalking(false);
    place(p, to, true);
    walking.current = false;
  }, [place, slotXY]);

  // Stand at the next unchecked desk whenever the tab or data changes -- but
  // never teleport mid-walk.
  useLayoutEffect(() => {
    if (cur && !walking.current) place(cur, target(cur), false);
  }, [cur, place]);

  useEffect(() => {
    const onResize = () => { if (cur && !walking.current) place(cur, target(cur), false); };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [cur, place]);

  // ---- actions -------------------------------------------------------------
  function withDone(p: Product, done: (s: Station, i: number) => boolean): LoopMapData | null {
    if (!data) return null;
    return { ...data, products: data.products.map((x) => x.slug !== p.slug ? x
      : { ...x, stations: x.stations.map((s, i) => ({ ...s, done: done(s, i) })) }) };
  }

  async function finishLap(p: Product) {
    await sleep(reduce() ? 0 : LAP_PAUSE_MS);
    const d = await load();
    const np = d?.products.find((x) => x.slug === p.slug);
    setSel(0);
    if (np) place(np, 0, false);
  }

  async function stepClick() {
    if (!cur || walking.current || busy) return;
    setArmed(null);
    const s = cur.stations[sel];
    const from = target(cur);
    const next = withDone(cur, (x, i) => (i === sel ? !s.done : x.done));
    const np = next?.products.find((x) => x.slug === cur.slug);
    if (!next || !np) return;
    setBusy(true);
    try {
      const res = await api(`/${cur.product_id}/steps/${s.step_order}/${s.done ? "undo" : "complete"}`, {});
      const to = target(np);
      if (to > from) walking.current = true; // hold the walker where it is until the walk starts
      setData(next);
      if (!s.done) { const nx = np.stations.findIndex((x) => !x.done); if (nx >= 0) setSel(nx); }
      if (to > from) await walkTo(np, from, to); else place(np, to, true);
      if (res.lap_completed) await finishLap(np); else void load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save that change.");
      walking.current = false;
      void load();
    } finally {
      setBusy(false);
    }
  }

  async function lapClick() {
    if (!cur || walking.current || busy) return;
    if (armed !== "lap") { setArmed("lap"); return; }
    setArmed(null);
    const from = target(cur);
    const next = withDone(cur, () => true);
    const np = next?.products.find((x) => x.slug === cur.slug);
    if (!next || !np) return;
    setBusy(true);
    try {
      await api(`/${cur.product_id}/laps/complete`, {});
      walking.current = true;
      setData(next);
      await walkTo(np, from, np.stations.length);
      await finishLap(np);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not record the lap.");
      walking.current = false;
      void load();
    } finally {
      setBusy(false);
    }
  }

  async function resetClick() {
    if (!cur || walking.current || busy) return;
    if (armed !== "reset") { setArmed("reset"); return; }
    setArmed(null);
    setBusy(true);
    try {
      await api(`/${cur.product_id}/laps/reset`, {});
      const d = await load();
      const np = d?.products.find((x) => x.slug === cur.slug);
      setSel(0);
      if (np) place(np, 0, true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not reset the lap.");
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    if (!cur) return;
    const text = draft.trim();
    if (!text) { document.getElementById("noteText")?.focus(); return; }
    setBusy(true);
    try {
      await api(`/${cur.product_id}/notes`, { step_order: cur.stations[sel].step_order, kind: isHole ? "hole" : "note", text: text.slice(0, 2000) });
      setDraft("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save the note. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function resolve(id: string, resolved: boolean) {
    try {
      await api(`/notes/${id}/resolve`, { resolved });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't update that note. Try again.");
    }
  }

  // ---- render --------------------------------------------------------------
  const st = cur?.stations[sel];
  const doneCount = cur?.stations.filter((s) => s.done).length ?? 0;
  const stepNotes = cur && st ? cur.notes.filter((n) => n.step_order === st.step_order) : [];
  const since = st ? daysSince(st.status_since) : null;
  const lane = laneHref(st?.lane_link ?? null);

  return (
    <div className="lm" onClickCapture={(e) => {
      if (armed && !(e.target as HTMLElement).closest("#doLap,#resetLap")) setArmed(null);
    }}>
      <link rel="stylesheet" precedence="default"
        href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Atkinson+Hyperlegible:wght@400;700&family=IBM+Plex+Mono:wght@400;600&display=swap" />
      <div className="wrap">
        <header>
          <h1>DECODED EMPIRE · LOOP MAP</h1>
          <p className="muted">Every product&apos;s path from stranger to paying customer. Mark a step complete and the worker walks to the next desk. Log a note on any step to record what&apos;s missing, even if you complete it anyway. Every note is kept in the Holes Log below.</p>
          <div className="asof">Desk colors: live system status, recomputed from production every 60 seconds{data ? ` · last ${fmt(data.generated_at)}` : ""}. Check marks and notes: yours.</div>
          {err ? <div className="save local">{err}</div>
            : <div className={`save ${data ? "ok" : "local"}`}>{data ? "Saved to CEO Decoded · checks and notes sync across devices." : "Loading live status…"}</div>}
          <div className="legend">
            <span className="s-ok"><i className="dot" />Working, proven</span>
            <span className="s-warn"><i className="dot" />Built, not proven</span>
            <span className="s-you"><i className="dot" />Waiting on you</span>
            <span className="s-stop"><i className="dot" />Blocked</span>
            <span className="s-none"><i className="dot" />Not built</span>
            <span className="s-unk"><i className="dot" />Unknown (can&apos;t read the source)</span>
          </div>
        </header>

        <WaitingStrip products={products} />

        <nav className="tabs" role="tablist">
          {products.map((p) => {
            const h = openHoles(p);
            return (
              <button key={p.slug} className="tab" role="tab" id={`t-${p.slug}`} aria-selected={p.slug === cur?.slug} onClick={() => show(p.slug)}>
                {p.name}{h ? <span className="holes">{h}</span> : null}
              </button>
            );
          })}
        </nav>

        {cur && st ? (
          <section className="office">
            <div className="ohead">
              <div className="left">
                <h3>{cur.name}</h3>
                <div className="playbook">{cur.playbook_line}</div>
                <div className="lapline">
                  Lap {cur.lap} · {doneCount} of {cur.stations.length} steps done
                  {cur.laps_finished ? ` · ${cur.laps_finished} lap${cur.laps_finished > 1 ? "s" : ""} finished, last ${fmt(cur.last_lap_at)}` : ""}
                </div>
              </div>
              <div className="actions">
                <button id="doLap" className={`btn ${armed === "lap" ? "arm" : "go"}`} onClick={lapClick} disabled={busy && armed !== "lap"}>
                  {armed === "lap" ? "CONFIRM: FINISH LAP?" : "✓ COMPLETE WHOLE LOOP"}
                </button>
                <button id="resetLap" className={`btn ${armed === "reset" ? "arm" : ""}`} onClick={resetClick} disabled={!doneCount}>
                  {armed === "reset" ? "CONFIRM: CLEAR CHECKS?" : "RESET LAP"}
                </button>
              </div>
            </div>

            <div className="track" ref={trackRef}>
              {cur.stations.map((s, i) => (
                <Desk key={s.step_order} s={s} i={i} sel={sel} p={cur} onSelect={(k) => setSel(k)} />
              ))}
              <div className="slot" data-slot={cur.stations.length}><div className="goal">🏁<br />LAP DONE</div></div>
              <div className={`walker${isWalking ? " walking" : ""}`} ref={walkerRef}>
                <Sprite />
                {bubble ? <div className="bubble">{bubble}</div> : null}
              </div>
            </div>

            <div className="detail">
              <div className="card">
                <h2>STEP {sel + 1} · {st.name.toUpperCase()}</h2>
                <dl>
                  <dt>WHAT</dt><dd>{st.description}</dd>
                  <dt>WHO</dt><dd>{st.owner === "you" ? "You" : "The system, on its own"}</dd>
                  <dt>STATUS</dt>
                  <dd className={`s-${CLS[st.status]}`}>
                    <b style={{ color: "var(--c)" }}>{LAB[st.status]}.</b> {st.evidence}
                    <div className="since">
                      {st.evidence_at ? `Evidence ${fmt(st.evidence_at)}` : "No evidence timestamp"}
                      {since != null ? ` · this status for ${since < 1 ? "under a day" : `${since} day${since === 1 ? "" : "s"}`}` : " · no history yet"}
                    </div>
                    {(st.evidence_link || lane) ? (
                      <div className="evlinks">
                        {st.evidence_link ? <a href={st.evidence_link} target="_blank" rel="noreferrer">Evidence ↗</a> : null}
                        {lane ? <a href={lane}>Go to the lane →</a> : null}
                      </div>
                    ) : null}
                  </dd>
                </dl>
                <p className="next"><b>To move forward:</b> {st.next_action}</p>
                <div className="stepctl">
                  <div className="row">
                    <button className={`btn ${st.done ? "" : "go"}`} onClick={stepClick} disabled={busy}>
                      {st.done ? "↺ UNDO COMPLETE" : "✓ MARK STEP COMPLETE"}
                    </button>
                    <span className="hint">{st.done ? "Done this lap." : "Completing is never blocked by a note."}</span>
                  </div>
                  <label htmlFor="noteText" className="hint">What happened at this step? Anything missing, broken, or slow?</label>
                  <textarea id="noteText" maxLength={2000} value={draft} onChange={(e) => setDraft(e.target.value)}
                    placeholder="e.g. Only found 2 buyers today; LinkedIn search for Moovx came up empty." />
                  <div className="row">
                    <label className="hole"><input type="checkbox" checked={isHole} onChange={(e) => setIsHole(e.target.checked)} /> This is a hole (something missing or broken)</label>
                    <button className="btn" onClick={saveNote} disabled={busy}>SAVE NOTE</button>
                  </div>
                  <h2>NOTES ON THIS STEP ({stepNotes.length})</h2>
                  {stepNotes.length ? (
                    <ul className="notes">
                      {stepNotes.map((n) => (
                        <li key={n.id} className={`note${n.kind === "hole" ? " h" : ""}${n.resolved_at ? " r" : ""}`}>
                          <div className="meta">
                            {n.kind === "hole" ? <span className="tag">HOLE</span> : <span className="tag n">NOTE</span>}
                            {n.resolved_at ? <span className="tag d">RESOLVED</span> : null}
                            <span>{fmt(n.created_at)}</span>
                            <span>lap {n.lap}</span>
                            {n.kind === "hole" ? (
                              <button className="linkbtn" onClick={() => resolve(n.id, !n.resolved_at)}>{n.resolved_at ? "Reopen" : "Mark resolved"}</button>
                            ) : null}
                          </div>
                          <div className="txt">{n.text}</div>
                        </li>
                      ))}
                    </ul>
                  ) : <p className="empty">No notes yet. Notes you save here stay on record, even after the step is complete.</p>}
                </div>
              </div>

              <div className="card">
                <div className={`verdict s-${cur.verdict.tone ?? "none"}`}>
                  <h2>DOES THIS STRATEGY WORK?</h2>
                  <p style={{ marginTop: 8 }}><b>{cur.verdict.title}</b> {cur.verdict.body}</p>
                </div>
                <table className="math"><tbody>
                  {cur.math.map((r) => <tr key={r[0]}><td>{r[0]}</td><td>{r[1]}</td></tr>)}
                </tbody></table>
                {cur.chips.length ? (
                  <div className="chips">
                    {cur.chips.map((c) => c.live && c.status
                      ? <span key={c.text} className={`chip s-${CLS[c.status]}`} title={c.evidence}>{c.text.split(":")[0]}: {LAB[c.status].toLowerCase()}</span>
                      : <span key={c.text} className={`chip s-${c.tone}`}>{c.text}</span>)}
                  </div>
                ) : null}
              </div>
            </div>

            {cur.funnel ? (
              <div className="card">
                <h2>WEEKLY FUNNEL · LAST EIGHT WEEKS</h2>
                <div className="tblwrap"><table className="tbl funnel">
                  <thead><tr>
                    <th>Week of</th>
                    <th className="n">Qualified<span className="src">AUTO</span></th>
                    <th className="n">Approved<span className="src">AUTO</span></th>
                    <th className="n">Sent<span className="src">AUTO</span></th>
                    <th className="n">Replies<span className="src you">YOUR MARK</span></th>
                    <th className="n">Calls<span className="src you">YOUR MARK</span></th>
                    <th className="n">Won<span className="src you">YOUR MARK</span></th>
                  </tr></thead>
                  <tbody>
                    {cur.funnel.map((w) => (
                      <tr key={w.week}>
                        <td className="mono">{w.week}</td>
                        <td className="n">{w.qualified}</td><td className="n">{w.approved}</td><td className="n">{w.sent}</td>
                        <td className="n">{w.replies}</td><td className="n">{w.calls}</td><td className="n">{w.won}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
                <p className="hint">AUTO columns are written by the pipeline. YOUR MARK columns come from what you mark in Marketing → Outreach → Conversations, so a reply you haven&apos;t marked isn&apos;t counted.</p>
              </div>
            ) : null}
          </section>
        ) : (
          <section className="office"><p className="empty">{err ? "The Loop Map couldn't load. The error is shown above." : "Loading the office floor…"}</p></section>
        )}

        <HolesLog products={products} showAll={showAll} setShowAll={setShowAll} onResolve={resolve} />
        <ReferenceSections counters={data?.counters ?? null} />
      </div>
    </div>
  );
}
