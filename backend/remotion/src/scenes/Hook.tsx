import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import { Bokeh } from "../components/Atmosphere";
import { Words } from "../components/Words";
import { alpha, BODY, clamp } from "../theme";
import type { HookScene } from "../types";
import { fitSize, type SceneEnv } from "./shared";

// Rapid questions, one every two beats, then the punchline in the accent colour.
export const Hook: React.FC<{ scene: HookScene } & SceneEnv> = ({ scene, palette, beatFrames }) => {
  const frame = useCurrentFrame();
  const step = beatFrames * 2;
  const punchAt = beatFrames * (1 + 2 * scene.lines.length);
  const punchIn = interpolate(frame, [punchAt - 2, punchAt + 6], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 80%, ${alpha(palette.accent, 0.16)} 0%, ${palette.bg} 65%)` }}>
      <Bokeh color={palette.accent} count={14} opacity={0.25} />
      <AbsoluteFill style={{ justifyContent: "center", padding: 80 }}>
        {scene.lines.map((line, i) => (
          <Sequence key={i} from={beatFrames * (1 + 2 * i)} durationInFrames={step} layout="none">
            <Words text={line} size={fitSize(line, 128)} color={palette.ink} />
          </Sequence>
        ))}
        <Sequence from={punchAt} layout="none">
          <div style={{ opacity: punchIn }}>
            {scene.lead ? (
              <div style={{ fontFamily: BODY, fontWeight: 700, fontSize: 52, color: palette.muted, textAlign: "center", marginBottom: 18 }}>{scene.lead}</div>
            ) : null}
            <Words text={scene.punch} size={fitSize(scene.punch, 132)} color={palette.accent} start={2} />
          </div>
        </Sequence>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
