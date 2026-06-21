import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, FONT } from "./style";

/* ----------------------------------------------------------------- easing */
const easeOut = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInOut = (x: number) =>
  x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

/* ----------------------------------------------------------------- logo mark
   A classical institution mark (pediment + columns) — "intelligence grade". */
export const LogoMark: React.FC<{ size?: number; color?: string; stroke?: number }>
  = ({ size = 120, color = C.cream, stroke = 2.4 }) => (
  <svg width={size} height={size} viewBox="0 0 100 100" fill="none">
    {/* pediment */}
    <path d="M14 34 L50 14 L86 34 Z" stroke={color} strokeWidth={stroke} strokeLinejoin="round" />
    {/* architrave */}
    <rect x="18" y="38" width="64" height="6" stroke={color} strokeWidth={stroke} />
    {/* columns */}
    {[26, 39, 52, 65].map((x) => (
      <line key={x} x1={x + 2} y1={48} x2={x + 2} y2={78} stroke={color} strokeWidth={stroke} strokeLinecap="round" />
    ))}
    {/* base */}
    <rect x="16" y="80" width="68" height="6" stroke={color} strokeWidth={stroke} />
    <line x1="12" y1="90" x2="88" y2="90" stroke={color} strokeWidth={stroke} strokeLinecap="round" />
  </svg>
);

/* ----------------------------------------------------------------- ambient texture */
export const Vignette: React.FC<{ strength?: number }> = ({ strength = 0.55 }) => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(120% 120% at 50% 42%, rgba(0,0,0,0) 45%, rgba(0,0,0,${strength}) 100%)`,
      pointerEvents: "none",
    }}
  />
);

export const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.05 }) => {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>`;
  return (
    <AbsoluteFill
      style={{
        backgroundImage: `url("data:image/svg+xml;utf8,${svg}")`,
        opacity,
        mixBlendMode: "overlay",
        pointerEvents: "none",
      }}
    />
  );
};

/* A faint navy field with a slow drifting highlight — used behind type scenes. */
export const NavyField: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / durationInFrames;
  const gx = 50 + 18 * Math.sin(p * Math.PI * 2);
  const gy = 38 + 10 * Math.cos(p * Math.PI * 2);
  return (
    <AbsoluteFill style={{ backgroundColor: C.navy }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(80% 70% at ${gx}% ${gy}%, ${C.inkSurface} 0%, ${C.navy} 60%)`,
        }}
      />
      <Grain opacity={0.045} />
      <Vignette strength={0.5} />
    </AbsoluteFill>
  );
};

/* ----------------------------------------------------------------- Ken Burns screenshot */
type Dir = "in" | "out" | "left" | "right" | "up";
export const KenBurnsShot: React.FC<{
  src: string;
  dir?: Dir;
  durationInFrames: number;
  brightness?: number;
}> = ({ src, dir = "in", durationInFrames, brightness = 1 }) => {
  const frame = useCurrentFrame();
  const p = easeInOut(interpolate(frame, [0, durationInFrames], [0, 1], { extrapolateRight: "clamp" }));
  let scale = 1.08;
  let tx = 0;
  let ty = 0;
  const amt = 0.09;
  if (dir === "in") scale = interpolate(p, [0, 1], [1.04, 1.16]);
  if (dir === "out") scale = interpolate(p, [0, 1], [1.16, 1.04]);
  if (dir === "left") { scale = 1.14; tx = interpolate(p, [0, 1], [amt, -amt]) * 100; }
  if (dir === "right") { scale = 1.14; tx = interpolate(p, [0, 1], [-amt, amt]) * 100; }
  if (dir === "up") { scale = 1.14; ty = interpolate(p, [0, 1], [amt, -amt]) * 100; }
  return (
    <AbsoluteFill style={{ backgroundColor: C.navy, overflow: "hidden" }}>
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "top center",
          transform: `scale(${scale}) translate(${tx}px, ${ty}px)`,
          filter: `brightness(${brightness})`,
        }}
      />
    </AbsoluteFill>
  );
};

/* A floating "device" panel variant — screenshot framed with shadow over navy. */
export const PanelShot: React.FC<{ src: string; durationInFrames: number; drift?: number }>
  = ({ src, durationInFrames, drift = 1 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200, mass: 0.7 } });
  const p = interpolate(frame, [0, durationInFrames], [0, 1]);
  const y = interpolate(enter, [0, 1], [60, 0]) + Math.sin(p * Math.PI) * -6 * drift;
  const scale = interpolate(enter, [0, 1], [0.94, 1]) * interpolate(p, [0, 1], [1, 1.03]);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          width: 1480,
          borderRadius: 16,
          overflow: "hidden",
          transform: `translateY(${y}px) scale(${scale})`,
          boxShadow: "0 60px 120px rgba(0,0,0,0.55), 0 0 0 1px rgba(183,199,235,0.15)",
          opacity: enter,
        }}
      >
        <Img src={staticFile(src)} style={{ width: "100%", display: "block" }} />
      </div>
    </AbsoluteFill>
  );
};

/* ----------------------------------------------------------------- captions */
export const Eyebrow: React.FC<{ children: React.ReactNode; color?: string }> = ({ children, color = C.accent }) => (
  <div
    style={{
      fontFamily: FONT.sans,
      fontWeight: 700,
      fontSize: 22,
      letterSpacing: "0.28em",
      textTransform: "uppercase",
      color,
    }}
  >
    {children}
  </div>
);

/* Lower-third caption over a screenshot, with a navy scrim for legibility. */
export const LowerThird: React.FC<{
  eyebrow: string;
  title: React.ReactNode;
  durationInFrames: number;
  accent?: string;
}> = ({ eyebrow, title, durationInFrames, accent = C.accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200, mass: 0.6 }, durationInFrames: 22 });
  const exit = interpolate(frame, [durationInFrames - 14, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const y = interpolate(enter, [0, 1], [40, 0]);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", opacity: exit }}>
      <div
        style={{
          height: "52%",
          background: `linear-gradient(to top, rgba(4,22,50,0.96) 8%, rgba(4,22,50,0.78) 38%, rgba(4,22,50,0) 100%)`,
        }}
      />
      <div style={{ position: "absolute", left: 96, bottom: 92, transform: `translateY(${y}px)`, opacity: enter }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
          <div style={{ width: 46, height: 3, background: accent }} />
          <Eyebrow color={accent}>{eyebrow}</Eyebrow>
        </div>
        <div
          style={{
            fontFamily: FONT.serif,
            fontWeight: 600,
            fontSize: 72,
            lineHeight: 1.04,
            color: C.cream,
            maxWidth: 1180,
            letterSpacing: "-0.01em",
          }}
        >
          {title}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* Persistent corner branding to tie scenes together. */
export const Watermark: React.FC<{ dark?: boolean }> = ({ dark = false }) => {
  const color = dark ? "rgba(25,28,30,0.55)" : "rgba(244,241,234,0.72)";
  return (
    <div style={{ position: "absolute", top: 52, left: 96, display: "flex", alignItems: "center", gap: 14 }}>
      <LogoMark size={30} color={color} stroke={3} />
      <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 17, letterSpacing: "0.26em", color, textTransform: "uppercase" }}>
        Nessus Intelligence
      </div>
    </div>
  );
};

/* ----------------------------------------------------------------- count-up number */
export const CountUp: React.FC<{
  to: number;
  startFrame?: number;
  durationFrames?: number;
  format?: (n: number) => string;
}> = ({ to, startFrame = 0, durationFrames = 42, format }) => {
  const frame = useCurrentFrame();
  const p = easeOut(interpolate(frame, [startFrame, startFrame + durationFrames], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const value = Math.round(to * p);
  const fmt = format ?? ((n: number) => n.toLocaleString("en-US"));
  return <>{fmt(value)}</>;
};

export { easeOut, easeInOut };
