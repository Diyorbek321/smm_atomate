import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Icon } from "../components/Icon";
import { Words } from "../components/Words";
import { alpha, BODY, clamp } from "../theme";
import type { FeatureScene } from "../types";
import { fitSize, type SceneEnv } from "./shared";

// "01 — LABEL" eyebrow, kinetic title, a drawn icon and one supporting line.
export const Feature: React.FC<{ scene: FeatureScene } & SceneEnv> = ({ scene, palette, beatFrames }) => {
  const frame = useCurrentFrame();
  const rule = interpolate(frame, [0, 18], [0, 1], clamp);
  const sub = interpolate(frame, [beatFrames * 2, beatFrames * 2 + 14], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${palette.bg} 0%, ${alpha(palette.brand, 0.22)} 100%)` }}>
      <div style={{ position: "absolute", top: 170, left: 90, right: 90 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 22, fontFamily: BODY, fontWeight: 800, fontSize: 38, color: palette.accent }}>
          <span>{scene.index}</span>
          <div style={{ height: 5, width: 120 * rule, background: palette.accent, borderRadius: 3 }} />
          <span style={{ letterSpacing: 6, textTransform: "uppercase" }}>{scene.label}</span>
        </div>
        <div style={{ marginTop: 34 }}>
          <Words text={scene.title} size={fitSize(scene.title, 112)} align="left" start={4} color={palette.ink} accent={scene.accent} accentColor={palette.accent} />
        </div>
        <div style={{ marginTop: 26, fontFamily: BODY, fontWeight: 600, fontSize: 46, lineHeight: 1.3, color: palette.muted, opacity: sub }}>{scene.subtitle}</div>
      </div>
      <div style={{ position: "absolute", top: 1060, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
        <Icon name={scene.icon} color={palette.accent} start={beatFrames} size={380} />
      </div>
    </AbsoluteFill>
  );
};
