import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, FONT } from "./style";
import { CountUp, Grain, LogoMark, Vignette } from "./components";

export const BEAT = 12; // frames per beat @ 150bpm / 30fps

const easeOut = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInOut = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
// deterministic pseudo-random (Math.random would flicker across parallel render workers)
const rand = (i: number) => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};

/* ----------------------------------------------------------------- animated backdrop */
export const GraphField: React.FC<{ intensity?: number }> = ({ intensity = 1 }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const shift = (frame * 0.5) % 52;
  const gx = 50 + 26 * Math.sin(frame / 80);
  const gy = 42 + 14 * Math.cos(frame / 64);
  return (
    <AbsoluteFill style={{ backgroundColor: C.navy }}>
      <AbsoluteFill style={{ background: `radial-gradient(72% 62% at ${gx}% ${gy}%, ${C.inkSurface} 0%, ${C.navy} 66%)` }} />
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(rgba(183,199,235,0.20) 1.5px, transparent 1.7px)`,
          backgroundSize: `52px 52px`,
          backgroundPosition: `${shift}px ${shift}px`,
          opacity: 0.45 * intensity,
          WebkitMaskImage: "radial-gradient(85% 85% at 50% 45%, black, transparent)",
          maskImage: "radial-gradient(85% 85% at 50% 45%, black, transparent)",
        }}
      />
      <svg width={width} height={height} style={{ position: "absolute" }}>
        {Array.from({ length: 7 }).map((_, i) => {
          const y = 120 + i * 140;
          const len = interpolate((frame + i * 24) % 130, [0, 65, 130], [0, width, 0]);
          return <line key={i} x1={0} y1={y} x2={len} y2={y} stroke="rgba(183,199,235,0.08)" strokeWidth={1} />;
        })}
      </svg>
      <Vignette strength={0.55} />
    </AbsoluteFill>
  );
};

/* white flash at local frame 0 */
export const Flash: React.FC<{ strength?: number; len?: number }> = ({ strength = 0.5, len = 6 }) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [0, 1, len], [0, strength, 0], { extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ background: C.cream, opacity: o, pointerEvents: "none" }} />;
};

/* expanding shockwave ring */
const Shockwave: React.FC<{ at: number; color?: string }> = ({ at, color = C.accent }) => {
  const frame = useCurrentFrame();
  const p = clamp01((frame - at) / 18);
  if (p <= 0 || p >= 1) return null;
  const r = interpolate(p, [0, 1], [10, 340]);
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        width: r * 2,
        height: r * 2,
        marginLeft: -r,
        marginTop: -r,
        borderRadius: "50%",
        border: `2px solid ${color}`,
        opacity: (1 - p) * 0.6,
      }}
    />
  );
};

/* consistent caption for graphic scenes */
export const GCaption: React.FC<{ eyebrow: string; title: React.ReactNode; accent?: string; delay?: number }>
  = ({ eyebrow, title, accent = C.accent, delay = 4 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inSp = spring({ frame: frame - delay, fps, config: { damping: 200, mass: 0.5 } });
  return (
    <div style={{ position: "absolute", left: 96, bottom: 80, opacity: inSp, transform: `translateY(${interpolate(inSp, [0, 1], [22, 0])}px)` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12 }}>
        <div style={{ width: 40, height: 3, background: accent }} />
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 20, letterSpacing: "0.26em", textTransform: "uppercase", color: accent }}>{eyebrow}</div>
      </div>
      <div style={{ fontFamily: FONT.serif, fontWeight: 600, fontSize: 58, color: C.cream, lineHeight: 1.05, letterSpacing: "-0.01em" }}>{title}</div>
    </div>
  );
};

const Watermark: React.FC = () => (
  <div style={{ position: "absolute", top: 50, left: 96, display: "flex", alignItems: "center", gap: 12, opacity: 0.7 }}>
    <LogoMark size={26} color={C.cream} stroke={3} />
    <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 15, letterSpacing: "0.26em", color: C.cream, textTransform: "uppercase" }}>Nessus Intelligence</div>
  </div>
);

/* ================================================================= INTRO */
export const IntroFast: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const draw = clamp01(frame / 16);
  const logoSp = spring({ frame, fps, config: { damping: 200, mass: 0.7 } });
  const word = spring({ frame: frame - 8, fps, config: { damping: 12, mass: 0.6, stiffness: 120 } });
  const tagW = interpolate(frame, [22, 40], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const track = interpolate(frame, [16, 40], [0.9, 0.62], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  // build-to-drop: a ring closes + zoom punch near the end
  const punch = interpolate(frame, [78, 95], [1, 1.16], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const beamH = interpolate(frame, [60, 96], [0, 1], { extrapolateLeft: "clamp" });
  return (
    <AbsoluteFill style={{ transform: `scale(${punch})` }}>
      <GraphField />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ transform: `scale(${interpolate(logoSp, [0, 1], [0.6, 1])})`, opacity: logoSp, marginBottom: 18, clipPath: `inset(${(1 - draw) * 100}% 0 0 0)` }}>
          <LogoMark size={120} color={C.cream} stroke={2.2} />
        </div>
        <div style={{ fontFamily: FONT.serif, fontWeight: 700, fontSize: 92, color: C.cream, transform: `scale(${interpolate(word, [0, 1], [0.7, 1])})`, opacity: clamp01(word) }}>NESSUS</div>
        <div style={{ fontFamily: FONT.sans, fontWeight: 600, fontSize: 24, letterSpacing: `${track}em`, marginLeft: `${track}em`, color: C.accent, marginTop: 8, opacity: tagW }}>INTELLIGENCE</div>
        <div style={{ width: interpolate(tagW, [0, 1], [0, 360]), height: 1, background: C.gold, marginTop: 26 }} />
        <div style={{ fontFamily: FONT.serif, fontStyle: "italic", fontSize: 28, color: C.creamDim, marginTop: 22, opacity: tagW }}>Canadian political due diligence.</div>
      </AbsoluteFill>
      {/* drop beam */}
      <div style={{ position: "absolute", left: "50%", bottom: 0, width: 2, height: `${beamH * 100}%`, marginLeft: -1, background: `linear-gradient(to top, ${C.accent}, transparent)`, opacity: 0.5 }} />
      <Vignette strength={0.6} />
    </AbsoluteFill>
  );
};

/* ================================================================= STAT SLAM */
const STATS = [
  { to: 1150000, label: "Federal Contracts", sub: "two decades of procurement" },
  { to: 6200000, label: "Political Donations", sub: "every contributor on record" },
  { to: 363000, label: "Lobbying Records", sub: "who lobbied whom" },
  { to: 343, label: "Members of Parliament", sub: "and the bills they touch", fmt: (n: number) => String(n) },
];
const SLAM = 36; // frames per stat (3 beats)
const StatOne: React.FC<{ s: (typeof STATS)[number] }> = ({ s }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sp = spring({ frame, fps, config: { damping: 11, mass: 0.55, stiffness: 140 } });
  const scale = interpolate(sp, [0, 1], [1.35, 1]);
  const out = interpolate(frame, [SLAM - 5, SLAM], [1, 0], { extrapolateLeft: "clamp" });
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: out }}>
      <Shockwave at={0} />
      <div style={{ transform: `scale(${scale})`, opacity: clamp01(sp * 1.4) }}>
        <div style={{ fontFamily: FONT.mono, fontWeight: 600, fontSize: 200, color: C.cream, lineHeight: 1, letterSpacing: "-0.04em", textAlign: "center" }}>
          <CountUp to={s.to} startFrame={2} durationFrames={14} format={s.fmt} />
        </div>
      </div>
      <div style={{ width: 70, height: 3, background: C.gold, margin: "26px 0 18px", opacity: clamp01(sp) }} />
      <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 30, letterSpacing: "0.22em", textTransform: "uppercase", color: C.accent, opacity: clamp01(sp) }}>{s.label}</div>
      <div style={{ fontFamily: FONT.serif, fontStyle: "italic", fontSize: 26, color: C.creamDim, marginTop: 10, opacity: clamp01(sp) }}>{s.sub}</div>
    </AbsoluteFill>
  );
};
export const StatSlam: React.FC = () => (
  <AbsoluteFill>
    <GraphField intensity={1.1} />
    <Watermark />
    <div style={{ position: "absolute", top: 120, width: "100%", textAlign: "center", fontFamily: FONT.sans, fontWeight: 700, fontSize: 22, letterSpacing: "0.34em", textTransform: "uppercase", color: C.accent, opacity: 0.85 }}>The Corpus</div>
    {STATS.map((s, i) => (
      <Sequence key={i} from={i * SLAM} durationInFrames={SLAM} layout="none">
        <StatOne s={s} />
      </Sequence>
    ))}
    <Vignette strength={0.5} />
  </AbsoluteFill>
);

/* ================================================================= SOURCES UNIFY */
const SOURCES = ["Contracts", "Donations", "Lobbying", "Bills", "Gazette", "Hansard", "Grants", "Tribunals", "News"];
export const SourcesUnify: React.FC = () => {
  const frame = useCurrentFrame();
  const cx = 960;
  const cy = 470;
  const conv = easeInOut(clamp01((frame - 18) / 34)); // converge 18->52
  const settle = spring({ frame: frame - 52, fps: 30, config: { damping: 14, mass: 0.5 } });
  return (
    <AbsoluteFill>
      <GraphField />
      <Watermark />
      {SOURCES.map((label, i) => {
        const ang = (i / SOURCES.length) * Math.PI * 2 - Math.PI / 2;
        const R = 430 + rand(i) * 90;
        const sx = cx + Math.cos(ang) * R;
        const sy = cy + Math.sin(ang) * R * 0.62;
        const x = interpolate(conv, [0, 1], [sx, cx]);
        const y = interpolate(conv, [0, 1], [sy, cy]);
        const op = interpolate(conv, [0, 0.7, 1], [1, 1, 0]);
        const appear = clamp01((frame - i * 2) / 8);
        return (
          <div key={label} style={{ position: "absolute", left: x, top: y, transform: "translate(-50%,-50%)", opacity: op * appear }}>
            <div style={{ fontFamily: FONT.sans, fontWeight: 600, fontSize: 24, color: C.cream, background: "rgba(27,43,72,0.85)", border: `1px solid ${C.accent}55`, padding: "10px 20px", borderRadius: 999, whiteSpace: "nowrap" }}>{label}</div>
          </div>
        );
      })}
      {/* central unified node */}
      <div style={{ position: "absolute", left: cx, top: cy, transform: `translate(-50%,-50%) scale(${interpolate(settle, [0, 1], [0.2, 1])})`, opacity: clamp01(settle) }}>
        <div style={{ width: 132, height: 132, borderRadius: "50%", background: `radial-gradient(circle, ${C.accent} 0%, ${C.inkSurface} 70%)`, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 70px ${C.accent}66` }}>
          <LogoMark size={66} color={C.navy} stroke={3} />
        </div>
      </div>
      <Shockwave at={52} />
      <GCaption eyebrow="One Layer" title={<>Nine federal sources.<br />One intelligence layer.</>} delay={40} />
      <Vignette strength={0.5} />
    </AbsoluteFill>
  );
};

/* ================================================================= ENTITY MERGE (moat) */
const VARIANTS = [
  { t: "TELUS Communications Inc.", x: 560, y: 300 },
  { t: "TELUS COMMUNICATIONS COMPANY", x: 1380, y: 330 },
  { t: "Telus Communications", x: 520, y: 660 },
  { t: "TELUS Corp.", x: 1400, y: 690 },
];
export const EntityMerge: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cx = 960;
  const cy = 460;
  const merge = easeInOut(clamp01((frame - 44) / 22)); // 44->66 fly to center
  const canon = spring({ frame: frame - 66, fps, config: { damping: 12, mass: 0.5, stiffness: 130 } });
  return (
    <AbsoluteFill>
      <GraphField intensity={1.1} />
      <Watermark />
      {VARIANTS.map((v, i) => {
        const drift = Math.sin((frame + i * 11) / 9) * 6;
        const x = interpolate(merge, [0, 1], [v.x, cx]);
        const y = interpolate(merge, [0, 1], [v.y + drift, cy]);
        const op = interpolate(frame, [4 + i * 3, 12 + i * 3, 60, 66], [0, 1, 1, 0], { extrapolateRight: "clamp" });
        const sc = interpolate(merge, [0, 1], [1, 0.7]);
        return (
          <div key={i} style={{ position: "absolute", left: x, top: y, transform: `translate(-50%,-50%) scale(${sc})`, opacity: op }}>
            <div style={{ fontFamily: FONT.mono, fontWeight: 500, fontSize: 26, color: C.creamDim, background: "rgba(27,43,72,0.7)", border: "1px solid rgba(183,199,235,0.25)", padding: "12px 22px", borderRadius: 10, whiteSpace: "nowrap" }}>{v.t}</div>
          </div>
        );
      })}
      <Flash strength={0.45} len={6} />
      {/* canonical node */}
      <div style={{ position: "absolute", left: cx, top: cy, transform: `translate(-50%,-50%) scale(${interpolate(canon, [0, 1], [0.3, 1])})`, opacity: clamp01(canon) }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, background: C.cream, padding: "18px 34px", borderRadius: 14, boxShadow: `0 0 80px ${C.accent}88` }}>
          <div style={{ width: 34, height: 34, borderRadius: "50%", background: C.green, display: "flex", alignItems: "center", justifyContent: "center", color: C.cream, fontFamily: FONT.sans, fontWeight: 700, fontSize: 22 }}>✓</div>
          <span style={{ fontFamily: FONT.mono, fontWeight: 600, fontSize: 56, color: C.navy, letterSpacing: "-0.02em" }}>telus</span>
        </div>
      </div>
      <Shockwave at={66} color={C.green} />
      <GCaption eyebrow="The Moat" title={<>Entity resolution across<br />every source.</>} delay={70} />
      <Vignette strength={0.5} />
    </AbsoluteFill>
  );
};

/* ================================================================= CONNECTION WEB */
const WEB_NODES = ["Contracts", "Lobbying", "Bills", "Donations", "Gazette", "Hansard", "News"];
export const ConnectionWeb: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const cx = 960;
  const cy = 450;
  const R = 300;
  const centerSp = spring({ frame, fps, config: { damping: 200 } });
  return (
    <AbsoluteFill>
      <GraphField />
      <Watermark />
      <svg width={width} height={height} style={{ position: "absolute" }}>
        {WEB_NODES.map((label, i) => {
          const ang = (i / WEB_NODES.length) * Math.PI * 2 - Math.PI / 2;
          const nx = cx + Math.cos(ang) * R;
          const ny = cy + Math.sin(ang) * R;
          const dl = clamp01((frame - 6 - i * 4) / 12); // draw line
          const lx = interpolate(dl, [0, 1], [cx, nx]);
          const ly = interpolate(dl, [0, 1], [cy, ny]);
          // traveling pulse
          const pp = ((frame + i * 9) % 36) / 36;
          const px = cx + (nx - cx) * pp;
          const py = cy + (ny - cy) * pp;
          return (
            <g key={label}>
              <line x1={cx} y1={cy} x2={lx} y2={ly} stroke={`${C.accent}`} strokeWidth={2} opacity={0.5} />
              {dl > 0.95 && <circle cx={px} cy={py} r={4} fill={C.cream} opacity={0.9} />}
            </g>
          );
        })}
      </svg>
      {WEB_NODES.map((label, i) => {
        const ang = (i / WEB_NODES.length) * Math.PI * 2 - Math.PI / 2;
        const nx = cx + Math.cos(ang) * R;
        const ny = cy + Math.sin(ang) * R;
        const pop = spring({ frame: frame - 14 - i * 4, fps, config: { damping: 12, mass: 0.4, stiffness: 140 } });
        return (
          <div key={label} style={{ position: "absolute", left: nx, top: ny, transform: `translate(-50%,-50%) scale(${clamp01(pop)})`, opacity: clamp01(pop) }}>
            <div style={{ fontFamily: FONT.sans, fontWeight: 600, fontSize: 21, color: C.navy, background: C.cream, padding: "9px 18px", borderRadius: 999, whiteSpace: "nowrap", boxShadow: "0 6px 20px rgba(0,0,0,0.3)" }}>{label}</div>
          </div>
        );
      })}
      {/* center entity */}
      <div style={{ position: "absolute", left: cx, top: cy, transform: `translate(-50%,-50%) scale(${interpolate(centerSp, [0, 1], [0.4, 1])})`, opacity: centerSp }}>
        <div style={{ width: 120, height: 120, borderRadius: "50%", background: `radial-gradient(circle, ${C.accent} 0%, ${C.inkSurface} 72%)`, boxShadow: `0 0 60px ${C.accent}77`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONT.mono, fontWeight: 600, fontSize: 30, color: C.navy }}>telus</div>
      </div>
      <GCaption eyebrow="Cross-Source" title={<>Every connection,<br />decoded automatically.</>} accent={C.amber} delay={30} />
      <Vignette strength={0.5} />
    </AbsoluteFill>
  );
};

/* ================================================================= RISK BARS */
const RISKS = [
  { sector: "Telecommunications", score: 9.0 },
  { sector: "Energy & Pipelines", score: 8.5 },
  { sector: "Banking & Finance", score: 7.8 },
  { sector: "Aerospace & Defence", score: 7.2 },
  { sector: "Pharmaceuticals", score: 6.6 },
];
const riskColor = (s: number) => (s >= 8 ? C.red : s >= 6.5 ? C.amber : C.green);
export const RiskBars: React.FC = () => {
  const frame = useCurrentFrame();
  const maxW = 1000;
  return (
    <AbsoluteFill>
      <GraphField />
      <Watermark />
      <div style={{ position: "absolute", left: 120, top: 180 }}>
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 22, letterSpacing: "0.28em", textTransform: "uppercase", color: C.accent, marginBottom: 10 }}>Sector Risk · 0–10</div>
        <div style={{ fontFamily: FONT.serif, fontWeight: 600, fontSize: 50, color: C.cream, marginBottom: 44 }}>Political risk, scored.</div>
        {RISKS.map((r, i) => {
          const p = easeOut(clamp01((frame - 6 - i * 6) / 22));
          const w = (r.score / 10) * maxW * p;
          return (
            <div key={r.sector} style={{ display: "flex", alignItems: "center", marginBottom: 26 }}>
              <div style={{ width: 420, fontFamily: FONT.sans, fontWeight: 600, fontSize: 28, color: C.cream }}>{r.sector}</div>
              <div style={{ width: maxW, height: 26, background: "rgba(183,199,235,0.12)", borderRadius: 999, overflow: "hidden" }}>
                <div style={{ width: w, height: "100%", background: riskColor(r.score), borderRadius: 999, boxShadow: `0 0 24px ${riskColor(r.score)}88` }} />
              </div>
              <div style={{ width: 110, textAlign: "right", fontFamily: FONT.mono, fontWeight: 600, fontSize: 34, color: riskColor(r.score) }}>
                <CountUp to={Math.round(r.score * 10)} startFrame={6 + i * 6} durationFrames={22} format={(n) => (n / 10).toFixed(1)} />
              </div>
            </div>
          );
        })}
      </div>
      <Vignette strength={0.5} />
    </AbsoluteFill>
  );
};

/* ================================================================= PROOF FLASHES */
const PROOF = [
  { src: "shots/dashboard.png", label: "Command Center" },
  { src: "shots/sector_telecom.png", label: "Sector Intelligence" },
  { src: "shots/entity_telus.png", label: "Entity Profile" },
  { src: "shots/search.png", label: "Ask Nessus" },
  { src: "shots/record_contract.png", label: "Any Record" },
  { src: "shots/players.png", label: "343 Players" },
];
const FLASH_LEN = 19;
const ProofOne: React.FC<{ src: string; label: string; i: number }> = ({ src, label, i }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sp = spring({ frame, fps, config: { damping: 16, mass: 0.5, stiffness: 130 } });
  const tilt = (i % 2 === 0 ? -1 : 1) * 2.2;
  const x = interpolate(sp, [0, 1], [(i % 2 === 0 ? -80 : 80), 0]);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <Flash strength={0.3} len={4} />
      <div style={{ transform: `translateX(${x}px) scale(${interpolate(sp, [0, 1], [0.9, 1.02])}) rotate(${tilt}deg)`, opacity: clamp01(sp * 1.5), width: 1380, borderRadius: 16, overflow: "hidden", boxShadow: "0 50px 110px rgba(0,0,0,0.6), 0 0 0 1px rgba(183,199,235,0.18)" }}>
        <Img src={staticFile(src)} style={{ width: "100%", display: "block" }} />
      </div>
      <div style={{ position: "absolute", bottom: 120, fontFamily: FONT.sans, fontWeight: 700, fontSize: 26, letterSpacing: "0.2em", textTransform: "uppercase", color: C.cream, background: "rgba(4,22,50,0.8)", padding: "12px 28px", borderRadius: 999, border: `1px solid ${C.accent}55` }}>{label}</div>
    </AbsoluteFill>
  );
};
export const ProofFlash: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: C.navy }}>
    <GraphField intensity={0.7} />
    <div style={{ position: "absolute", top: 70, width: "100%", textAlign: "center", fontFamily: FONT.serif, fontWeight: 600, fontSize: 40, color: C.cream }}>Live. Real federal data.</div>
    {PROOF.map((p, i) => (
      <Sequence key={i} from={i * FLASH_LEN} durationInFrames={FLASH_LEN + 2} layout="none">
        <ProofOne src={p.src} label={p.label} i={i} />
      </Sequence>
    ))}
  </AbsoluteFill>
);

/* ================================================================= ASK NESSUS GFX */
const Q = "Telecom lobbying before the spectrum auction?";
const ANSWER = [
  "4 bills in motion · 2,910 lobbying communications",
  "Engagement tracks the legislative agenda",
];
const PILLS = ["Bills", "Lobbying", "Gov News"];
export const AskNessusGfx: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const chars = Math.floor(interpolate(frame, [2, 16], [0, Q.length], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const cardSp = spring({ frame: frame - 14, fps, config: { damping: 16, mass: 0.45 } });
  const cursorOn = Math.floor(frame / 5) % 2 === 0;
  return (
    <AbsoluteFill>
      <GraphField />
      <Watermark />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: 1180 }}>
          {/* query bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 18, background: "rgba(27,43,72,0.9)", border: `1px solid ${C.accent}66`, borderRadius: 16, padding: "24px 30px" }}>
            <LogoMark size={34} color={C.accent} stroke={3} />
            <span style={{ fontFamily: FONT.sans, fontWeight: 500, fontSize: 34, color: C.cream }}>
              {Q.slice(0, chars)}
              <span style={{ opacity: cursorOn && chars < Q.length ? 1 : 0, color: C.accent }}>|</span>
            </span>
          </div>
          {/* answer card */}
          <div style={{ marginTop: 26, background: C.cream, borderRadius: 16, padding: "30px 36px", opacity: clamp01(cardSp), transform: `translateY(${interpolate(cardSp, [0, 1], [26, 0])}px)`, boxShadow: "0 40px 100px rgba(0,0,0,0.5)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18 }}>
              <div style={{ width: 26, height: 26, borderRadius: "50%", background: C.green, color: C.cream, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONT.sans, fontWeight: 700, fontSize: 17 }}>✓</div>
              <span style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 18, letterSpacing: "0.2em", textTransform: "uppercase", color: C.muted }}>Cited Answer</span>
            </div>
            {ANSWER.map((line, i) => (
              <div key={i} style={{ fontFamily: FONT.serif, fontSize: 30, color: C.ink, marginBottom: 10, opacity: clamp01((frame - 22 - i * 5) / 7) }}>• {line}</div>
            ))}
            <div style={{ display: "flex", gap: 12, marginTop: 20 }}>
              {PILLS.map((p, i) => (
                <span key={p} style={{ fontFamily: FONT.sans, fontWeight: 600, fontSize: 19, color: C.navy, background: "#eaf0fb", border: `1px solid ${C.navy}22`, padding: "7px 16px", borderRadius: 999, opacity: clamp01((frame - 32 - i * 4) / 7) }}>{p}</span>
              ))}
            </div>
          </div>
        </div>
      </AbsoluteFill>
      <GCaption eyebrow="Ask Nessus" title={<>Ask anything. Cited answers.</>} accent={C.green} delay={6} />
      <Vignette strength={0.5} />
    </AbsoluteFill>
  );
};

/* ================================================================= CLOSE */
export const CloseFast: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sp = spring({ frame, fps, config: { damping: 13, mass: 0.6, stiffness: 130 } });
  const tag = interpolate(frame, [12, 28], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const lineW = interpolate(frame, [16, 44], [0, 440], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill>
      <GraphField intensity={0.8} />
      <Flash strength={0.5} len={6} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20, transform: `scale(${interpolate(sp, [0, 1], [0.7, 1])})`, opacity: clamp01(sp) }}>
          <LogoMark size={62} color={C.cream} stroke={2.6} />
          <div style={{ fontFamily: FONT.serif, fontWeight: 700, fontSize: 72, color: C.cream, letterSpacing: "0.03em" }}>NESSUS</div>
          <div style={{ fontFamily: FONT.sans, fontWeight: 600, fontSize: 19, letterSpacing: "0.48em", color: C.accent, alignSelf: "center", marginTop: 8 }}>INTELLIGENCE</div>
        </div>
        <div style={{ width: lineW, height: 1, background: C.gold, marginTop: 30 }} />
        <div style={{ fontFamily: FONT.serif, fontStyle: "italic", fontSize: 40, color: C.cream, marginTop: 26, opacity: tag }}>See the whole board.</div>
        <div style={{ fontFamily: FONT.sans, fontWeight: 500, fontSize: 19, letterSpacing: "0.22em", textTransform: "uppercase", color: C.creamDim, marginTop: 20, opacity: tag }}>Federal intelligence · entity-resolved</div>
      </AbsoluteFill>
      <Vignette strength={0.62} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};
