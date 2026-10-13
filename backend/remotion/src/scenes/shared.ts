import type { Palette } from "../types";

/** What every scene gets besides its own copy. Frames are local to the scene. */
export type SceneEnv = { palette: Palette; beatFrames: number; frames: number };

/** Font size that keeps a headline of `text` inside `width` px; Unbounded caps run ~0.95em per glyph. */
export const fitSize = (text: string, max: number, width = 920): number => {
  const longest = Math.max(...text.split(/\s+/).map((w) => w.length), 1);
  return Math.round(Math.min(max, width / (longest * 0.95)));
};
