import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Words } from "../components/Words";
import { BODY } from "../theme";
import type { ListScene } from "../types";
import { fitSize, type SceneEnv } from "./shared";

// Title plus checklist items that pop in one per beat, on the accent colour.
export const List: React.FC<{ scene: ListScene } & SceneEnv> = ({ scene, palette, beatFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: palette.accent }}>
      <div style={{ position: "absolute", top: 260, left: 90, right: 90 }}>
        <Words text={scene.title} size={fitSize(scene.title, 118)} align="left" color={palette.bg} accent={scene.accent} accentColor={palette.ink} />
      </div>
      <div style={{ position: "absolute", top: 820, left: 90, right: 90, display: "flex", flexDirection: "column", gap: 40 }}>
        {scene.items.map((item, i) => {
          const s = spring({ frame: frame - beatFrames * (2 + i), fps, config: { damping: 15 } });
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 30, opacity: s, transform: `translateX(${(1 - s) * -120}px)`, fontFamily: BODY, fontWeight: 800, fontSize: 56, lineHeight: 1.2, color: palette.bg }}>
              <div style={{ width: 70, height: 70, borderRadius: 20, background: palette.bg, color: palette.accent, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 42, flexShrink: 0 }}>✓</div>
              {item}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
