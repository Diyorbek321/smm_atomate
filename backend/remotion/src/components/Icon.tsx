import { interpolate, useCurrentFrame } from "remotion";
import { evolvePath } from "@remotion/paths";
import type { IconName } from "../types";
import { alpha, clamp } from "../theme";

// 100x100 stroke icons; drawn on with evolvePath.
const PATHS: Record<IconName, string> = {
  bolt: "M58 8 L22 56 L48 56 L40 92 L78 40 L52 40 Z",
  wallet: "M12 30 L80 30 Q88 30 88 38 L88 80 Q88 88 80 88 L20 88 Q12 88 12 80 Z M64 52 L88 52 L88 68 L64 68 Z M12 30 L66 12 L72 30",
  shield: "M50 8 L86 22 L86 50 Q86 78 50 92 Q14 78 14 50 L14 22 Z M34 50 L46 62 L68 38",
  star: "M50 8 L62 36 L92 38 L68 58 L76 88 L50 72 L24 88 L32 58 L8 38 L38 36 Z",
  clock: "M50 10 A40 40 0 1 1 49.9 10 Z M50 28 L50 52 L66 62",
  heart: "M50 86 L16 52 Q4 38 14 24 Q28 8 50 30 Q72 8 86 24 Q96 38 84 52 Z",
  check: "M50 10 A40 40 0 1 1 49.9 10 Z M30 52 L44 66 L72 36",
  pin: "M50 92 Q18 58 18 38 A32 32 0 1 1 82 38 Q82 58 50 92 Z M50 26 A12 12 0 1 1 49.9 26 Z",
  users: "M36 44 A14 14 0 1 1 35.9 44 Z M8 88 Q10 60 36 60 Q62 60 64 88 M68 30 A12 12 0 1 1 67.9 30 Z M70 56 Q90 58 92 84",
  book: "M50 22 Q34 12 12 14 L12 82 Q34 80 50 90 Q66 80 88 82 L88 14 Q66 12 50 22 Z M50 22 L50 90",
};

type Props = { name: IconName; color: string; start?: number; size?: number };

export const Icon: React.FC<Props> = ({ name, color, start = 0, size = 320 }) => {
  const frame = useCurrentFrame();
  const draw = interpolate(frame, [start, start + 36], [0, 1], clamp);
  const fill = interpolate(frame, [start + 28, start + 50], [0, 1], clamp);
  const d = PATHS[name] ?? PATHS.star;
  const evolved = evolvePath(draw, d);
  return (
    <svg width={size} height={size} viewBox="-6 -6 112 112">
      <path d={d} fill={alpha(color, fill * 0.16)} stroke={color} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={evolved.strokeDasharray} strokeDashoffset={evolved.strokeDashoffset} />
    </svg>
  );
};
