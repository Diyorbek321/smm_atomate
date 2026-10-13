import { useCurrentFrame } from "remotion";
import type { Pattern as PatternName } from "../types";

type Props = { kind: PatternName; a: string; b: string; size?: number; direction?: 1 | -1 };

// A moving decorative band: taxi checker, diagonal stripes or a dot row.
export const PatternBand: React.FC<Props> = ({ kind, a, b, size = 40, direction = 1 }) => {
  const shift = ((useCurrentFrame() * 5 * direction) % (size * 2)) - size * 2;
  const cells = Array.from({ length: Math.ceil(1080 / size) + 4 });

  if (kind === "checker") {
    return (
      <div style={{ overflow: "hidden", height: size * 2 }}>
        {[0, 1].map((r) => (
          <div key={r} style={{ display: "flex", transform: `translateX(${shift}px)` }}>
            {cells.map((_, c) => (
              <div key={c} style={{ width: size, height: size, flexShrink: 0, background: (r + c) % 2 === 0 ? a : b }} />
            ))}
          </div>
        ))}
      </div>
    );
  }
  if (kind === "dots") {
    return (
      <div style={{ overflow: "hidden", height: size, display: "flex", alignItems: "center", gap: size * 0.6, transform: `translateX(${shift}px)` }}>
        {cells.map((_, c) => (
          <div key={c} style={{ width: size * 0.4, height: size * 0.4, borderRadius: "50%", flexShrink: 0, background: a }} />
        ))}
      </div>
    );
  }
  return (
    <div
      style={{
        height: size * 1.5,
        backgroundImage: `repeating-linear-gradient(-45deg, ${a} 0 ${size / 2}px, ${b} ${size / 2}px ${size}px)`,
        backgroundPosition: `${shift}px 0`,
      }}
    />
  );
};
