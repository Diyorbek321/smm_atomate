import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Faces ship with the backend (app/assets/fonts); `npm run fonts` copies them in.
export const DISPLAY = "Unbounded";
export const BODY = "Manrope";

export const fontsReady = Promise.all([
  loadFont({ family: DISPLAY, url: staticFile("fonts/Unbounded.ttf"), weight: "200 900" }),
  loadFont({ family: BODY, url: staticFile("fonts/Manrope.ttf"), weight: "200 800" }),
]);

/** `#rrggbb` + alpha -> rgba(). Falls back to white for anything malformed. */
export const alpha = (hex: string, a: number): string => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return `rgba(255,255,255,${a})`;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
