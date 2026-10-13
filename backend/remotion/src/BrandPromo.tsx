import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import { CameraPush, Grain, LightLeak, Vignette } from "./components/Atmosphere";
import { Cta } from "./scenes/Cta";
import { Feature } from "./scenes/Feature";
import { Hook } from "./scenes/Hook";
import { List } from "./scenes/List";
import { Logo } from "./scenes/Logo";
import type { SceneEnv } from "./scenes/shared";
import { Stat } from "./scenes/Stat";
import { clamp } from "./theme";
import type { PromoProps, Scene } from "./types";

const LEAK_FRAMES = 30;
const ENTER_FRAMES = 9;

const SceneBody: React.FC<{ scene: Scene } & SceneEnv> = ({ scene, ...env }) => {
  switch (scene.type) {
    case "hook":
      return <Hook scene={scene} {...env} />;
    case "logo":
      return <Logo scene={scene} {...env} />;
    case "feature":
      return <Feature scene={scene} {...env} />;
    case "list":
      return <List scene={scene} {...env} />;
    case "stat":
      return <Stat scene={scene} {...env} />;
    case "cta":
      return <Cta scene={scene} {...env} />;
  }
};

/** Hard cut hidden by a quick scale + blur settle; the light leak sits on top. */
const Enter: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [0, ENTER_FRAMES], [0, 1], { ...clamp, easing: (t) => 1 - Math.pow(1 - t, 3) });
  return <AbsoluteFill style={{ transform: `scale(${1.06 - 0.06 * p})`, filter: `blur(${(1 - p) * 12}px)` }}>{children}</AbsoluteFill>;
};

export const BrandPromo: React.FC<PromoProps> = ({ fps, beat, palette, scenes }) => {
  const beatFrames = Math.round(beat * fps);
  const spans = scenes.map((scene) => {
    const from = Math.round(scene.at[0] * fps);
    return { scene, from, frames: Math.max(1, Math.round(scene.at[1] * fps) - from) };
  });

  return (
    <AbsoluteFill style={{ backgroundColor: palette.bg }}>
      {spans.map(({ scene, from, frames }, i) => (
        <Sequence key={i} from={from} durationInFrames={frames}>
          <Enter>
            <CameraPush frames={frames}>
              <SceneBody scene={scene} palette={palette} beatFrames={beatFrames} frames={frames} />
            </CameraPush>
          </Enter>
        </Sequence>
      ))}
      {spans.slice(1).map(({ from }, i) => (
        <Sequence key={`leak-${i}`} from={Math.max(0, from - LEAK_FRAMES / 2)} durationInFrames={LEAK_FRAMES}>
          <LightLeak frames={LEAK_FRAMES} flip={i % 2 === 1} />
        </Sequence>
      ))}
      <Grain />
      <Vignette />
    </AbsoluteFill>
  );
};
