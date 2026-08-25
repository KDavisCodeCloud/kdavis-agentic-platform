"use client";

import { useEffect, useMemo, useRef } from "react";
import type { NovaVoiceState } from "@/lib/types";

// Faithful React recreation of jarvis-decoded/NOVA Multi-agent HUD
// Interface/design_handoff_nova_hud/NOVA HUD.dc.html -- the design's own
// README explicitly says to recreate it in the target codebase's real
// environment, not run the .dc.html file directly (it depends on Claude
// Design's own runtime, not included in the export). Pixel geometry,
// timings, and canvas renderers are ported 1:1 from that file's
// `PALETTE`/`Component` class. Real difference from the prototype: `mode`
// here is driven entirely by the `state` prop (NOVA's real voice-loop
// state via Supabase Realtime), never by an internal auto-cycle timer or
// node clicks -- see the design's own README acknowledging per-node
// state binding is "the natural place," not something actually built
// into the prototype. Only NOVA's own global ring/core system reflects
// live state in this version; the four side nodes are static labels,
// dimmed when their agent is disabled.

const PALETTE: Record<
  NovaVoiceState,
  {
    hex: string;
    rgb: string;
    sd: string;
    sdf: string;
    pulse: string;
    sonar: string;
    strobe: string;
    amp: number;
    orbit: number;
    orbSpeed: number;
    word: string;
    label: string;
  }
> = {
  idle: {
    hex: "#00f0ff", rgb: "0,240,255", sd: "26s", sdf: "11s", pulse: "5.5s", sonar: "4.2s", strobe: "0s",
    amp: 0.22, orbit: 14, orbSpeed: 0.28, word: "STANDBY", label: "IDLE",
  },
  listening: {
    hex: "#0066ff", rgb: "0,102,255", sd: "18s", sdf: "8s", pulse: "2.6s", sonar: "2.1s", strobe: "0s",
    amp: 0.62, orbit: 22, orbSpeed: 0.5, word: "LISTENING", label: "LISTENING",
  },
  thinking: {
    hex: "#ffaa00", rgb: "255,170,0", sd: "7s", sdf: "2.6s", pulse: "1.4s", sonar: "1.5s", strobe: "0s",
    amp: 0.45, orbit: 46, orbSpeed: 1.5, word: "PROCESSING", label: "THINKING",
  },
  talking: {
    hex: "#00ff88", rgb: "0,255,136", sd: "14s", sdf: "5s", pulse: "1.1s", sonar: "1.9s", strobe: "0s",
    amp: 1, orbit: 26, orbSpeed: 0.8, word: "REPLYING", label: "TALKING",
  },
  error: {
    hex: "#ff0044", rgb: "255,0,68", sd: "5s", sdf: "1.8s", pulse: ".5s", sonar: ".9s", strobe: ".22s",
    amp: 0.8, orbit: 34, orbSpeed: 2.2, word: "ALERT", label: "FAULT",
  },
};

const ORDER: NovaVoiceState[] = ["idle", "listening", "thinking", "talking", "error"];

interface HudNode {
  slug: "apollo" | "counsel" | "ledger" | "board";
  label: string;
  enabled: boolean;
}

interface NovaHudProps {
  state: NovaVoiceState;
  nodes: HudNode[];
  glow?: number;
}

type LandRing = [number, number, number][]; // [lonRad, sinLat, cosLat]

interface Particle {
  a: number;
  r: number;
  s: number;
  z: number;
}

export function NovaHud({ state, nodes, glow = 1 }: NovaHudProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const globeLRef = useRef<HTMLCanvasElement>(null);
  const globeRRef = useRef<HTMLCanvasElement>(null);
  const waveLRef = useRef<HTMLCanvasElement>(null);
  const waveRRef = useRef<HTMLCanvasElement>(null);
  const orbitRef = useRef<HTMLCanvasElement>(null);

  const bars = useRef<number[]>(new Array(96).fill(0.1));
  const bars2 = useRef<number[]>(new Array(96).fill(0.1));
  const particles = useRef<Particle[]>(
    Array.from({ length: 60 }, () => ({
      a: Math.random() * Math.PI * 2,
      r: 150 + Math.random() * 200,
      s: (0.15 + Math.random() * 0.5) * (Math.random() < 0.35 ? -1 : 1),
      z: 0.4 + Math.random() * 0.6,
    }))
  );
  const land = useRef<LandRing[] | null>(null);
  const landCache = useRef<Map<HTMLCanvasElement, { key: string; cv: HTMLCanvasElement }>>(new Map());
  const t = useRef(0);
  const half = useRef(false);
  const tickRef = useRef(0);

  const pal = PALETTE[state];

  // --- load real-geography land polygons once (public domain, version-pinned) ---
  useEffect(() => {
    fetch("https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json")
      .then((r) => r.json())
      .then((topo: any) => {
        const tr = topo.transform;
        const sc = tr.scale;
        const tl = tr.translate;
        const arc = (i: number): [number, number][] => {
          const rev = i < 0;
          if (rev) i = ~i;
          let x = 0;
          let y = 0;
          const out: [number, number][] = topo.arcs[i].map((d: [number, number]) => {
            x += d[0];
            y += d[1];
            return [x * sc[0] + tl[0], y * sc[1] + tl[1]];
          });
          return rev ? out.slice().reverse() : out;
        };
        const rings: LandRing[] = [];
        const addPoly = (poly: number[][]) =>
          poly.forEach((ring) => {
            let pts: [number, number][] = [];
            ring.forEach((i) => {
              const a = arc(i);
              pts = pts.length ? pts.concat(a.slice(1)) : a;
            });
            if (pts.length < 4) return;
            const step = pts.length > 120 ? 3 : pts.length > 40 ? 2 : 1;
            const dec = pts.filter((_, k) => k % step === 0);
            rings.push(
              dec.map((p) => {
                const la = (p[1] * Math.PI) / 180;
                return [(p[0] * Math.PI) / 180, Math.sin(la), Math.cos(la)];
              })
            );
          });
        topo.objects.countries.geometries.forEach((g: any) => {
          if (g.type === "Polygon") addPoly(g.arcs);
          else if (g.type === "MultiPolygon") g.arcs.forEach(addPoly);
        });
        land.current = rings;
      })
      .catch(() => {});
  }, []);

  // --- apply CSS custom properties whenever state/glow changes ---
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    el.style.setProperty("--hud", pal.hex);
    el.style.setProperty("--hud-soft", `rgba(${pal.rgb},${(0.3 * glow).toFixed(2)})`);
    el.style.setProperty("--sd", pal.sd);
    el.style.setProperty("--sdf", pal.sdf);
    el.style.setProperty("--pulse", pal.pulse);
    el.style.setProperty("--sonar", pal.sonar);
    el.style.setProperty("--strobe", pal.strobe === "0s" ? "9999s" : pal.strobe);
    el.style.filter = glow > 1 ? `saturate(1.1) brightness(${(0.9 + glow * 0.15).toFixed(2)})` : "none";
    el.style.transition = "filter .3s ease";
  }, [state, glow, pal]);

  // --- viewport scaling: design canvas is a fixed 1920x1080 stage ---
  useEffect(() => {
    const fit = () => {
      const el = rootRef.current;
      if (!el) return;
      const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
      el.style.transform = `scale(${s})`;
      el.style.transformOrigin = "center center";
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  // --- 30fps render loop (every other rAF) + slow tick for numeric readouts ---
  useEffect(() => {
    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      half.current = !half.current;
      if (half.current) return;
      t.current += 1 / 30;
      const p = PALETTE[state];
      drawGlobe(globeLRef.current, t.current * 0.35, p, land.current, landCache.current);
      drawGlobe(globeRRef.current, -t.current * 0.28 + 2.4, p, land.current, landCache.current);
      drawWave(waveLRef.current, bars.current, p, 1, t.current, state);
      drawWave(waveRRef.current, bars2.current, p, -1, t.current, state);
      drawOrbit(orbitRef.current, p, particles.current, state);
    };
    raf = requestAnimationFrame(frame);
    const slow = setInterval(() => {
      tickRef.current += 1;
    }, 2200);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(slow);
    };
  }, [state]);

  const nodeBySlug = useMemo(() => {
    const m: Record<string, HudNode> = {};
    for (const n of nodes) m[n.slug] = n;
    return m;
  }, [nodes]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "radial-gradient(120% 90% at 50% 45%, #071426 0%, #050b14 45%, #02060c 100%)",
        overflow: "hidden",
        fontFamily: "'Share Tech Mono', monospace",
      }}
    >
      <div
        ref={rootRef}
        style={
          {
            position: "relative",
            width: 1920,
            height: 1080,
            flex: "0 0 auto",
            color: "#00f0ff",
            "--hud": "#00f0ff",
            "--hud-soft": "rgba(0,240,255,.35)",
            "--sd": "22s",
            "--sdf": "9s",
            "--pulse": "5.5s",
            "--sonar": "3.4s",
            "--strobe": "0s",
          } as React.CSSProperties
        }
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "repeating-linear-gradient(to bottom, rgba(0,240,255,.045) 0 1px, transparent 1px 4px)",
            opacity: 0.5,
            pointerEvents: "none",
            mixBlendMode: "screen",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "radial-gradient(60% 50% at 50% 48%, rgba(0,240,255,.07), transparent 70%)",
            pointerEvents: "none",
          }}
        />

        {CORNER_POSITIONS.map((c) => (
          <div
            key={c.key}
            style={{
              position: "absolute",
              [c.h]: 22,
              [c.v]: 22,
              width: 74,
              height: 74,
              [`border${cap(c.h)}`]: "2px solid var(--hud)",
              [`border${cap(c.v)}`]: "2px solid var(--hud)",
              opacity: 0.9,
              boxShadow: "0 0 10px -2px var(--hud)",
            }}
          />
        ))}
        <div
          style={{
            position: "absolute",
            left: 96,
            top: 22,
            right: 96,
            height: 1,
            background: "linear-gradient(90deg,transparent,var(--hud) 12%,var(--hud) 88%,transparent)",
            opacity: 0.45,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 96,
            bottom: 22,
            right: 96,
            height: 1,
            background: "linear-gradient(90deg,transparent,var(--hud) 12%,var(--hud) 88%,transparent)",
            opacity: 0.45,
          }}
        />

        <CircuitNetwork />

        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 42,
            textAlign: "center",
            fontFamily: "Orbitron, sans-serif",
            fontWeight: 700,
            fontSize: 26,
            letterSpacing: 14,
            color: "var(--hud)",
            textShadow: "0 0 22px var(--hud)",
            opacity: 0.95,
          }}
        >
          THE HUSTLE DECODED EMPIRE
        </div>

        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 92,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <div
              style={{
                fontFamily: "Orbitron, sans-serif",
                fontWeight: 900,
                fontSize: 24,
                letterSpacing: 7,
                color: "var(--hud)",
                textShadow: "0 0 18px var(--hud)",
              }}
            >
              {pal.word}
            </div>
            <div
              style={{
                position: "relative",
                width: 300,
                height: 16,
                border: "1px solid var(--hud)",
                boxShadow: "0 0 12px var(--hud) inset,0 0 10px var(--hud)",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: 2,
                  right: "auto",
                  width: 186,
                  background: "linear-gradient(90deg,rgba(0,240,255,.25),var(--hud))",
                  animation: "hudBreathe var(--pulse) ease-in-out infinite",
                }}
              />
            </div>
          </div>
        </div>

        {/* LEFT COLUMN */}
        <div style={{ position: "absolute", left: 60, top: 110, width: 300, display: "flex", flexDirection: "column", gap: 22 }}>
          <div style={{ position: "relative", height: 230 }}>
            <canvas ref={globeLRef} width={300} height={300} style={{ position: "absolute", left: 0, top: -6, width: 230, height: 230 }} />
          </div>
          <div style={{ fontFamily: "Orbitron, sans-serif", fontSize: 15, letterSpacing: 3, whiteSpace: "nowrap", opacity: 0.9 }}>
            WESTERN HEMISPHERE
          </div>
          <div style={{ borderTop: "1px solid var(--hud-soft)", borderBottom: "1px solid var(--hud-soft)", padding: "10px 0" }}>
            <canvas ref={waveLRef} width={440} height={140} style={{ width: 300, height: 90, display: "block" }} />
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div
          style={{
            position: "absolute",
            right: 60,
            top: 110,
            width: 300,
            display: "flex",
            flexDirection: "column",
            gap: 22,
            alignItems: "flex-end",
            textAlign: "right",
          }}
        >
          <div style={{ position: "relative", height: 230, width: "100%" }}>
            <canvas ref={globeRRef} width={300} height={300} style={{ position: "absolute", right: 0, top: -6, width: 230, height: 230 }} />
          </div>
          <div style={{ fontFamily: "Orbitron, sans-serif", fontSize: 15, letterSpacing: 3, whiteSpace: "nowrap", opacity: 0.9 }}>
            EASTERN HEMISPHERE
          </div>
          <div style={{ borderTop: "1px solid var(--hud-soft)", borderBottom: "1px solid var(--hud-soft)", padding: "10px 0", width: "100%" }}>
            <canvas ref={waveRRef} width={440} height={140} style={{ width: 300, height: 90, display: "block" }} />
          </div>
        </div>

        {/* NOVA CORE */}
        <div style={{ position: "absolute", left: 960, top: 530, width: 0, height: 0 }}>
          <div style={{ position: "absolute", left: -260, top: -260, width: 520, height: 520 }}>
            {[0, 1.1, 2.2].map((delay, i) => (
              <div
                key={i}
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: "50%",
                  border: `${i === 2 ? 1 : 2}px solid var(--hud)`,
                  opacity: [0.5, 0.4, 0.3][i],
                  animation: `hudSonar var(--sonar) ease-out infinite ${delay}s`,
                }}
              />
            ))}
            <div
              style={{
                position: "absolute",
                inset: 60,
                borderRadius: "50%",
                background: "radial-gradient(circle,var(--hud-soft),transparent 68%)",
                animation: "hudBreathe var(--pulse) ease-in-out infinite",
              }}
            />
            <canvas ref={orbitRef} width={640} height={640} style={{ position: "absolute", inset: 0, width: 520, height: 520 }} />
            <CoreRingSvg />
            <div
              style={{
                position: "absolute",
                inset: 0,
                borderRadius: "50%",
                border: "3px solid var(--hud)",
                opacity: 0,
                animation: "hudStrobe var(--strobe) steps(2) infinite",
                boxShadow: "0 0 40px var(--hud) inset",
              }}
            />
          </div>
          <div
            style={{
              position: "absolute",
              left: -170,
              top: -352,
              width: 340,
              textAlign: "center",
              fontFamily: "Orbitron, sans-serif",
              fontWeight: 900,
              fontSize: 46,
              letterSpacing: 12,
              color: "var(--hud)",
              textShadow: "0 0 28px var(--hud)",
            }}
          >
            NOVA
          </div>
          <div
            style={{
              position: "absolute",
              left: -200,
              top: -298,
              width: 400,
              textAlign: "center",
              fontSize: 14,
              letterSpacing: 6,
              opacity: 0.75,
            }}
          >
            PRIMARY VOICE CORE // {pal.label}
          </div>
        </div>

        {/* AGENT NODES */}
        <AgentNode slug="apollo" label="APOLLO" left={490} top={256} node={nodeBySlug.apollo} spinMul={1} spinRMul={0.7} innerMul={0.4} delay="0s" />
        <AgentNode slug="counsel" label="COUNSEL" left={1430} top={256} node={nodeBySlug.counsel} spinMul={1.1} spinRMul={0.8} innerMul={0.45} delay=".4s" reverse />
        <AgentNode slug="ledger" label="LEDGER" left={490} top={820} node={nodeBySlug.ledger} spinMul={1.25} spinRMul={0.9} innerMul={0.5} delay=".8s" />
        <AgentNode slug="board" label="BOARD" left={1430} top={820} node={nodeBySlug.board} spinMul={1.35} spinRMul={1} innerMul={0.55} delay="1.2s" reverse />

        <div style={{ position: "absolute", left: 520, right: 520, bottom: 66, display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", gap: 12 }}>
            {ORDER.map((m) => (
              <div
                key={m}
                style={{
                  padding: "9px 20px",
                  border: "1px solid var(--hud)",
                  fontFamily: "Orbitron, sans-serif",
                  fontSize: 13,
                  letterSpacing: 3,
                  background: m === state ? `rgba(${PALETTE[m].rgb},.22)` : "transparent",
                  color: PALETTE[m].hex,
                  boxShadow: m === state ? `0 0 18px ${PALETTE[m].hex}` : "none",
                }}
              >
                {PALETTE[m].label}
              </div>
            ))}
          </div>
        </div>
      </div>
      <style jsx global>{`
        @keyframes hudSpin { to { transform: rotate(360deg) } }
        @keyframes hudSpinR { to { transform: rotate(-360deg) } }
        @keyframes hudBreathe { 0%,100% { opacity:.4 } 50% { opacity:1 } }
        @keyframes hudDim { 0%,100% { opacity:.08 } 50% { opacity:.22 } }
        @keyframes hudDimCore { 0%,100% { opacity:.16 } 50% { opacity:.4 } }
        @keyframes hudSonar { 0% { transform:scale(.72); opacity:.85 } 100% { transform:scale(1.75); opacity:0 } }
        @keyframes hudStrobe { 0%,100% { opacity:0 } 50% { opacity:.5 } }
        @keyframes hudSweep { to { transform: rotate(360deg) } }
      `}</style>
    </div>
  );
}

// ---- small structural helpers ----

const CORNER_POSITIONS = [
  { key: "tl", h: "left", v: "top" },
  { key: "tr", h: "right", v: "top" },
  { key: "bl", h: "left", v: "bottom" },
  { key: "br", h: "right", v: "bottom" },
] as const;

function cap(s: string) {
  return s[0].toUpperCase() + s.slice(1);
}

function CircuitNetwork() {
  const paths = [
    "M700 470 H600 V300 H560",
    "M700 530 H520 V360 H452",
    "M1220 470 H1320 V300 H1360",
    "M1220 530 H1400 V360 H1468",
    "M700 590 H600 V760 H560",
    "M720 660 H520 V820 H452",
    "M1220 590 H1320 V760 H1360",
    "M1200 660 H1400 V820 H1468",
    "M690 610 H360 V500",
    "M1230 610 H1560 V500",
  ];
  return (
    <svg viewBox="0 0 1920 1080" style={{ position: "absolute", inset: 0, width: 1920, height: 1080, pointerEvents: "none", overflow: "visible" }}>
      <g fill="none" stroke="var(--hud)" strokeWidth={1.6} opacity={0.55}>
        {paths.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      <g fill="var(--hud)" fontFamily="'Share Tech Mono',monospace" fontSize={13} opacity={0.6} letterSpacing={2}>
        <text x={470} y={452}>TELEMETRY</text>
        <text x={1360} y={452}>TELEMETRY</text>
        <text x={470} y={642}>TELEMETRY</text>
        <text x={1360} y={642}>TELEMETRY</text>
      </g>
    </svg>
  );
}

function CoreRingSvg() {
  return (
    <svg viewBox="0 0 520 520" style={{ position: "absolute", inset: 0, width: 520, height: 520, overflow: "visible", filter: "drop-shadow(0 0 6px var(--hud))" }}>
      <g fill="none" stroke="var(--hud)">
        <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hudSpin var(--sd) linear infinite" }}>
          <circle cx={260} cy={260} r={252} strokeWidth={1.4} strokeDasharray="4 12" opacity={0.7} />
          <circle cx={260} cy={260} r={234} strokeWidth={6} strokeDasharray="90 42" opacity={0.85} />
        </g>
        <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hudSpinR var(--sdf) linear infinite" }}>
          <circle cx={260} cy={260} r={212} strokeWidth={2} strokeDasharray="30 10 4 10" opacity={0.8} />
          <circle cx={260} cy={260} r={196} strokeWidth={1} opacity={0.45} />
        </g>
        <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hudSpin calc(var(--sdf) * .62) linear infinite" }}>
          <circle cx={260} cy={260} r={168} strokeWidth={22} strokeDasharray="112 56" opacity={0.9} />
        </g>
        <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hudSpinR calc(var(--sd) * .5) linear infinite" }}>
          <circle cx={260} cy={260} r={140} strokeWidth={1.6} strokeDasharray="2 9" opacity={0.7} />
          <circle cx={260} cy={260} r={122} strokeWidth={10} strokeDasharray="60 30" opacity={0.8} />
        </g>
        <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hudSpin calc(var(--sdf) * 1.4) linear infinite" }}>
          <polygon points="260,152 353,206 353,314 260,368 167,314 167,206" strokeWidth={3} opacity={0.9} />
          <polygon points="260,172 336,216 336,304 260,348 184,304 184,216" strokeWidth={1} strokeDasharray="6 6" opacity={0.6} />
        </g>
        <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hudSpinR calc(var(--sdf) * .45) linear infinite" }} strokeWidth={2} opacity={0.95}>
          <path d="M260 196 V236 M260 284 V324 M212 260 H244 M276 260 H308" />
        </g>
      </g>
      <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hudSweep calc(var(--sdf) * .8) linear infinite" }}>
        <path d="M260 260 L260 40 A220 220 0 0 1 415 105 Z" fill="var(--hud)" opacity={0.07} />
      </g>
      <circle cx={260} cy={260} r={26} fill="var(--hud)" style={{ animation: "hudDimCore calc(var(--pulse) * .5) ease-in-out infinite" }} />
    </svg>
  );
}

function AgentNode({
  slug, label, left, top, node, spinMul, spinRMul, innerMul, delay, reverse,
}: {
  slug: string; label: string; left: number; top: number; node: HudNode | undefined;
  spinMul: number; spinRMul: number; innerMul: number; delay: string; reverse?: boolean;
}) {
  const enabled = node?.enabled ?? false;
  const spinA = reverse ? "hudSpinR" : "hudSpin";
  const spinB = reverse ? "hudSpin" : "hudSpinR";
  return (
    <div style={{ position: "absolute", left, top, width: 0, height: 0, opacity: enabled ? 1 : 0.35, transition: "opacity .3s ease" }}>
      <div style={{ position: "absolute", left: -110, top: -110, width: 220, height: 220, filter: "drop-shadow(0 0 10px var(--hud))" }}>
        <svg viewBox="0 0 220 220" style={{ position: "absolute", inset: 0, width: 220, height: 220, overflow: "visible" }} fill="none" stroke="var(--hud)">
          <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: `${spinA} calc(var(--sdf) * ${spinMul}) linear infinite` }}>
            <circle cx={110} cy={110} r={106} strokeWidth={8} strokeDasharray="70 32" opacity={0.85} />
          </g>
          <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: `${spinB} calc(var(--sdf) * ${spinRMul}) linear infinite` }}>
            <circle cx={110} cy={110} r={88} strokeWidth={16} strokeDasharray="44 26" opacity={0.8} />
          </g>
          <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: `${spinA} calc(var(--sd) * ${innerMul}) linear infinite` }}>
            <circle cx={110} cy={110} r={68} strokeWidth={1.4} strokeDasharray="3 8" opacity={0.65} />
          </g>
          <circle cx={110} cy={110} r={54} strokeWidth={2} opacity={0.85} />
          <circle cx={110} cy={110} r={54} fill="var(--hud)" stroke="none" style={{ animation: `hudDim var(--pulse) ease-in-out infinite ${delay}` }} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Orbitron, sans-serif", fontSize: 19, letterSpacing: 3, color: "#eafcff", textShadow: "0 0 10px var(--hud), 0 2px 6px #02060c" }}>
          {label}
        </div>
      </div>
      <div style={{ position: "absolute", left: -160, top: -166, width: 320, textAlign: "center", fontFamily: "Orbitron, sans-serif", fontWeight: 700, fontSize: 30, letterSpacing: 6, color: "var(--hud)", textShadow: "0 0 20px var(--hud)" }}>
        {label}
      </div>
    </div>
  );
}

// ---- canvas renderers (ported 1:1 from NOVA HUD.dc.html) ----

function drawGlobe(
  cv: HTMLCanvasElement | null,
  rot: number,
  p: (typeof PALETTE)[NovaVoiceState],
  landData: LandRing[] | null,
  cacheMap: Map<HTMLCanvasElement, { key: string; cv: HTMLCanvasElement }>
) {
  if (!cv) return;
  const c = cv.getContext("2d");
  if (!c) return;
  const W = cv.width;
  const R = W / 2 - 17;
  c.clearRect(0, 0, W, W);
  c.save();
  c.translate(W / 2, W / 2);
  c.strokeStyle = p.hex;
  c.shadowColor = p.hex;
  c.shadowBlur = 10;
  c.globalAlpha = 0.85;
  c.lineWidth = 2;
  c.beginPath();
  c.arc(0, 0, R, 0, Math.PI * 2);
  c.stroke();
  c.globalAlpha = 0.4;
  c.lineWidth = 1.1;
  c.shadowBlur = 6;
  for (let i = 1; i < 8; i++) {
    const y = -R + (2 * R * i) / 8;
    const rr = Math.sqrt(Math.max(R * R - y * y, 0));
    c.beginPath();
    c.ellipse(0, y, rr, rr * 0.16, 0, 0, Math.PI * 2);
    c.stroke();
  }
  for (let i = 0; i < 12; i++) {
    const ph = rot + (i * Math.PI) / 12;
    const w = Math.abs(Math.cos(ph)) * R;
    c.globalAlpha = 0.18 + Math.abs(Math.cos(ph)) * 0.35;
    c.beginPath();
    c.ellipse(0, 0, w, R, 0, 0, Math.PI * 2);
    c.stroke();
  }
  if (landData) {
    const stepKey = `${Math.round(rot / (Math.PI / 90))}|${p.hex}|${R}`;
    let cache = cacheMap.get(cv);
    if (!cache) {
      const offscreen = document.createElement("canvas");
      offscreen.width = W;
      offscreen.height = W;
      cache = { key: "", cv: offscreen };
      cacheMap.set(cv, cache);
    }
    if (cache.key !== stepKey) {
      cache.key = stepKey;
      const g = cache.cv.getContext("2d")!;
      g.clearRect(0, 0, W, W);
      g.save();
      g.translate(W / 2, W / 2);
      g.strokeStyle = p.hex;
      g.lineWidth = 1.2;
      g.globalAlpha = 0.78;
      const p0 = 0.36;
      const sp = Math.sin(p0);
      const cp = Math.cos(p0);
      const rr = Math.round(rot / (Math.PI / 90)) * (Math.PI / 90);
      g.beginPath();
      for (const ring of landData) {
        let started = false;
        for (const pt of ring) {
          const lo = pt[0] - rr;
          const cl = Math.cos(lo);
          if (sp * pt[1] + cp * pt[2] * cl <= 0) {
            started = false;
            continue;
          }
          const x = pt[2] * Math.sin(lo) * R;
          const y = -(cp * pt[1] - sp * pt[2] * cl) * R;
          if (started) g.lineTo(x, y);
          else {
            g.moveTo(x, y);
            started = true;
          }
        }
      }
      g.stroke();
      g.restore();
    }
    c.globalAlpha = 1;
    c.shadowBlur = 0;
    c.drawImage(cache.cv, -W / 2, -W / 2);
  }
  c.globalAlpha = 0.9;
  c.lineWidth = 1.6;
  c.shadowBlur = 12;
  const a = rot * 1.6;
  c.beginPath();
  c.arc(0, 0, R + 14, a, a + 1.1);
  c.stroke();
  c.beginPath();
  c.arc(0, 0, R + 14, a + Math.PI, a + Math.PI + 0.7);
  c.stroke();
  c.restore();
}

function drawWave(
  cv: HTMLCanvasElement | null,
  bars: number[],
  p: (typeof PALETTE)[NovaVoiceState],
  dir: number,
  time: number,
  mode: NovaVoiceState
) {
  if (!cv) return;
  const c = cv.getContext("2d");
  if (!c) return;
  const W = cv.width;
  const H = cv.height;
  const n = bars.length;
  const amp = p.amp;
  for (let i = 0; i < n; i++) {
    const env =
      mode === "talking"
        ? Math.abs(Math.sin(time * 5 + i * 0.35)) * (0.5 + 0.5 * Math.abs(Math.sin(time * 1.7)))
        : mode === "thinking"
        ? Math.abs(Math.sin(time * 9 + i)) * 0.5 + Math.random() * 0.3
        : mode === "error"
        ? Math.sin(time * 24) > 0
          ? Math.random()
          : 0.1
        : Math.abs(Math.sin(time * 1.2 + i * 0.18)) * 0.6 + Math.random() * 0.25;
    const target = 0.08 + env * amp;
    bars[i] += (target - bars[i]) * 0.22;
  }
  c.clearRect(0, 0, W, H);
  c.strokeStyle = p.hex;
  c.shadowColor = p.hex;
  c.shadowBlur = 8;
  c.lineWidth = 2.4;
  const step = W / n;
  for (let i = 0; i < n; i++) {
    const x = dir > 0 ? i * step + step / 2 : W - (i * step + step / 2);
    const h = bars[i] * H * 0.92;
    c.globalAlpha = 0.55 + bars[i] * 0.45;
    c.beginPath();
    c.moveTo(x, H / 2 - h / 2);
    c.lineTo(x, H / 2 + h / 2);
    c.stroke();
  }
  c.globalAlpha = 0.25;
  c.lineWidth = 1;
  c.shadowBlur = 0;
  c.beginPath();
  c.moveTo(0, H / 2);
  c.lineTo(W, H / 2);
  c.stroke();
}

function drawOrbit(
  cv: HTMLCanvasElement | null,
  p: (typeof PALETTE)[NovaVoiceState],
  parts: Particle[],
  mode: NovaVoiceState
) {
  if (!cv) return;
  const c = cv.getContext("2d");
  if (!c) return;
  const W = cv.width;
  const C = W / 2;
  c.clearRect(0, 0, W, W);
  c.save();
  c.translate(C, C);
  c.scale(W / 1040, W / 1040);
  c.fillStyle = p.hex;
  c.shadowColor = p.hex;
  c.shadowBlur = 12;
  const count = p.orbit;
  for (let i = 0; i < count; i++) {
    const q = parts[i % parts.length];
    q.a += q.s * p.orbSpeed * 0.02;
    const x = Math.cos(q.a) * q.r;
    const y = Math.sin(q.a) * q.r * 0.94;
    c.globalAlpha = 0.25 + q.z * 0.6;
    c.beginPath();
    c.arc(x, y, 1.6 + q.z * 2.6, 0, Math.PI * 2);
    c.fill();
    if (mode === "thinking" || mode === "error") {
      c.globalAlpha = 0.18;
      c.strokeStyle = p.hex;
      c.lineWidth = 1.4;
      c.beginPath();
      c.moveTo(x, y);
      c.lineTo(Math.cos(q.a - 0.18) * q.r, Math.sin(q.a - 0.18) * q.r * 0.94);
      c.stroke();
    }
  }
  c.restore();
}
