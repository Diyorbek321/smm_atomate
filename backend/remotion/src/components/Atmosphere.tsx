import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { noise2D } from "@remotion/noise";
import { alpha, clamp } from "../theme";

/** Slow dolly-in over a scene so nothing is ever perfectly static. */
export const CameraPush: React.FC<{ frames: number; children: React.ReactNode }> = ({ frames, children }) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, frames], [1, 1.045], clamp);
  const y = interpolate(frame, [0, frames], [0, -12], clamp);
  return <AbsoluteFill style={{ transform: `translateY(${y}px) scale(${scale})` }}>{children}</AbsoluteFill>;
};

/** Soft out-of-focus dots drifting upward. */
export const Bokeh: React.FC<{ color: string; count?: number; opacity?: number }> = ({ color, count = 18, opacity = 0.3 }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {Array.from({ length: count }).map((_, i) => {
        const size = 30 + ((i * 53) % 110);
        const x = ((i * 397) % 1080) + noise2D(`x${i}`, frame / 160, 0) * 60;
        const y = (((((i * 733) % 1920) - frame * (0.4 + (i % 4) * 0.25)) % 2100) + 2100) % 2100 - 90;
        const a = (0.35 + 0.65 * Math.abs(noise2D(`a${i}`, frame / 90, 1))) * opacity;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: size,
              height: size,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${alpha(color, a)} 0%, ${alpha(color, a * 0.4)} 45%, ${alpha(color, 0)} 70%)`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/** Animated film grain; the seed changes every two frames. */
export const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.07 }) => {
  const seed = Math.floor(useCurrentFrame() / 2);
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity, mixBlendMode: "overlay" }}>
      <svg width="100%" height="100%">
        <filter id={`grain-${seed}`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={seed} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter={`url(#grain-${seed})`} />
      </svg>
    </AbsoluteFill>
  );
};

/** Warm flare that sweeps across a cut, blended with `screen`. */
export const LightLeak: React.FC<{ frames: number; flip?: boolean }> = ({ frames, flip = false }) => {
  const p = useCurrentFrame() / frames;
  const opacity = interpolate(p, [0, 0.45, 1], [0, 0.85, 0], clamp);
  const x = interpolate(p, [0, 1], flip ? [1300, -300] : [-300, 1300]);
  return (
    <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen", opacity }}>
      <div style={{ position: "absolute", left: x - 700, top: 300, width: 1400, height: 1400, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,170,60,0.9) 0%, rgba(255,110,30,0.35) 35%, rgba(255,80,0,0) 70%)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 940, height: 26, background: "linear-gradient(90deg, rgba(255,200,120,0) 0%, rgba(255,230,180,0.9) 50%, rgba(255,200,120,0) 100%)", filter: "blur(6px)" }} />
    </AbsoluteFill>
  );
};

export const Vignette: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none", background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.45) 100%)" }} />
);
