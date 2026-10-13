import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { PatternBand } from "../components/Pattern";
import { BODY, clamp, DISPLAY } from "../theme";
import type { LogoScene } from "../types";
import { fitSize, type SceneEnv } from "./shared";

// Brand reveal on the accent colour, framed by a moving pattern band.
export const Logo: React.FC<{ scene: LogoScene } & SceneEnv> = ({ scene, palette, beatFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const name = spring({ frame: frame - 2, fps, config: { damping: 13 } });
  const tag = interpolate(frame, [beatFrames * 2, beatFrames * 2 + 14], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ backgroundColor: palette.accent }}>
      <div style={{ position: "absolute", top: 140, width: "100%" }}>
        <PatternBand kind={scene.pattern} a={palette.bg} b={palette.accent} />
      </div>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: 70 }}>
        <div
          style={{
            fontFamily: DISPLAY,
            fontWeight: 900,
            fontSize: fitSize(scene.name, 170),
            lineHeight: 1.02,
            textAlign: "center",
            color: palette.bg,
            letterSpacing: -4,
            transform: `scale(${0.6 + 0.4 * name})`,
            opacity: name,
          }}
        >
          {scene.name}
        </div>
        <div style={{ marginTop: 44, fontFamily: BODY, fontWeight: 800, fontSize: 54, textAlign: "center", color: palette.bg, opacity: tag, transform: `translateY(${(1 - tag) * 20}px)` }}>
          {scene.tagline}
        </div>
      </AbsoluteFill>
      <div style={{ position: "absolute", bottom: 140, width: "100%" }}>
        <PatternBand kind={scene.pattern} a={palette.bg} b={palette.accent} direction={-1} />
      </div>
    </AbsoluteFill>
  );
};
