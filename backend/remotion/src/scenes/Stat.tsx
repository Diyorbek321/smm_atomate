import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bokeh } from "../components/Atmosphere";
import { alpha, BODY, clamp, DISPLAY } from "../theme";
import type { StatScene } from "../types";
import type { SceneEnv } from "./shared";

// One big number counting up, landing on beat four, with its label below.
export const Stat: React.FC<{ scene: StatScene } & SceneEnv> = ({ scene, palette, beatFrames }) => {
  const frame = useCurrentFrame();
  const land = beatFrames * 4;
  const p = interpolate(frame, [4, land], [0, 1], { ...clamp, easing: (t) => 1 - Math.pow(1 - t, 3) });
  const value = Math.round(scene.value * p).toLocaleString("en-US").replace(/,/g, " ");
  const label = interpolate(frame, [land - 6, land + 10], [0, 1], clamp);
  // Unbounded digits run ~0.9em wide; size to the final value so the count never wraps.
  const glyphs = Math.round(scene.value).toLocaleString("en-US").length + scene.suffix.length * 0.5;
  const size = Math.round(Math.min(250, 900 / (glyphs * 0.9)));

  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 45%, ${alpha(palette.accent, 0.2)} 0%, ${palette.bg} 60%)`, justifyContent: "center", alignItems: "center", padding: 80 }}>
      <Bokeh color={palette.accent} count={12} opacity={0.2} />
      <div style={{ fontFamily: DISPLAY, fontWeight: 900, fontSize: size, lineHeight: 1, color: palette.accent, letterSpacing: -size * 0.03, whiteSpace: "nowrap" }}>
        {value}
        <span style={{ fontSize: size * 0.52 }}>{scene.suffix}</span>
      </div>
      <div style={{ marginTop: 40, fontFamily: BODY, fontWeight: 800, fontSize: 58, textAlign: "center", lineHeight: 1.25, color: palette.ink, opacity: label, transform: `translateY(${(1 - label) * 24}px)` }}>
        {scene.label}
      </div>
    </AbsoluteFill>
  );
};
