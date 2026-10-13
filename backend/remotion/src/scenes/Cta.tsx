import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Bokeh } from "../components/Atmosphere";
import { Words } from "../components/Words";
import { alpha, BODY, clamp, DISPLAY } from "../theme";
import type { CtaScene } from "../types";
import { fitSize, type SceneEnv } from "./shared";

// Sign-off: brand name, tagline, a pulsing button and the contact line.
export const Cta: React.FC<{ scene: CtaScene } & SceneEnv> = ({ scene, palette, beatFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const name = spring({ frame: frame - 2, fps, config: { damping: 14 } });
  const btnAt = beatFrames * 4;
  const btn = spring({ frame: frame - btnAt, fps, config: { damping: 11 } });
  const pulse = frame > btnAt + 20 ? 1 + Math.sin((frame - btnAt - 20) / 7) * 0.035 : 1;
  const contact = interpolate(frame, [btnAt + 10, btnAt + 26], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 35%, ${alpha(palette.accent, 0.18)} 0%, ${palette.bg} 65%)` }}>
      <Bokeh color={palette.accent} count={18} opacity={0.3} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: 80 }}>
        <div style={{ fontFamily: DISPLAY, fontWeight: 900, fontSize: fitSize(scene.name, 150), lineHeight: 1.02, textAlign: "center", color: palette.ink, letterSpacing: -4, opacity: name, transform: `translateY(${(1 - name) * 60}px)` }}>
          {scene.name}
        </div>
        <div style={{ marginTop: 60 }}>
          <Words text={scene.tagline} size={fitSize(scene.tagline, 70)} color={palette.ink} accent={scene.accent} accentColor={palette.accent} start={beatFrames * 2} stagger={3} />
        </div>
        <div style={{ marginTop: 70, padding: "34px 64px", borderRadius: 999, background: palette.accent, color: palette.bg, fontFamily: BODY, fontWeight: 800, fontSize: 54, textAlign: "center", transform: `scale(${btn * pulse})`, boxShadow: `0 24px 80px ${alpha(palette.accent, 0.45)}` }}>
          {scene.button}
        </div>
        {scene.contact ? (
          <div style={{ marginTop: 44, fontFamily: BODY, fontWeight: 700, fontSize: 48, color: palette.muted, opacity: contact }}>{scene.contact}</div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
