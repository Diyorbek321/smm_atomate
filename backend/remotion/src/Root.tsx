import { Composition } from "remotion";
import { BrandPromo } from "./BrandPromo";
import { SAMPLE } from "./sample";
import type { PromoProps } from "./types";

export const Root: React.FC = () => (
  <Composition
    id="BrandPromo"
    component={BrandPromo as unknown as React.FC<Record<string, unknown>>}
    defaultProps={SAMPLE as unknown as Record<string, unknown>}
    fps={SAMPLE.fps}
    width={SAMPLE.width}
    height={SAMPLE.height}
    durationInFrames={Math.round(SAMPLE.duration * SAMPLE.fps)}
    calculateMetadata={({ props }) => {
      const p = props as unknown as PromoProps;
      return { durationInFrames: Math.max(1, Math.round(p.duration * p.fps)), fps: p.fps, width: p.width, height: p.height };
    }}
  />
);
