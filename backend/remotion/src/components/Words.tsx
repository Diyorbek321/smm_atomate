import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY } from "../theme";

type Props = {
  text: string;
  start?: number;
  size?: number;
  color: string;
  accentColor?: string;
  accent?: string;
  align?: "left" | "center";
  stagger?: number;
};

// Kinetic headline: each word rises out of a mask with a spring and a blur-in.
// Words that appear in `accent` are painted in `accentColor`.
export const Words: React.FC<Props> = ({ text, start = 0, size = 110, color, accentColor, accent = "", align = "center", stagger = 4 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const accented = new Set(accent.toLowerCase().split(/\s+/).filter(Boolean));

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        justifyContent: align === "center" ? "center" : "flex-start",
        columnGap: size * 0.26,
        fontFamily: DISPLAY,
        fontWeight: 800,
        fontSize: size,
        lineHeight: 1.1,
        letterSpacing: -size * 0.025,
      }}
    >
      {text.split(/\s+/).filter(Boolean).map((word, i) => {
        const p = spring({ frame: frame - start - i * stagger, fps, config: { damping: 16, stiffness: 140 } });
        const bare = word.toLowerCase().replace(/[.,!?…:;—-]+$/g, "");
        return (
          <span key={i} style={{ overflow: "hidden", display: "inline-block", paddingBottom: size * 0.1 }}>
            <span
              style={{
                display: "inline-block",
                transform: `translateY(${(1 - p) * 110}%)`,
                filter: `blur(${Math.max(0, 1 - p) * 10}px)`,
                color: accentColor && accented.has(bare) ? accentColor : color,
              }}
            >
              {word}
            </span>
          </span>
        );
      })}
    </div>
  );
};
