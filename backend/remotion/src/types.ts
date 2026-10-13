/**
 * Props contract with the Python side (app/services/remotion_script.py).
 * Python owns timing and copy; this package owns layout and motion only.
 * All times are seconds; `at` is [start, end) on the clip timeline.
 */
export type Palette = {
  bg: string;
  ink: string;
  accent: string;
  brand: string;
  muted: string;
};

export type IconName = "bolt" | "wallet" | "shield" | "star" | "clock" | "heart" | "check" | "pin" | "users" | "book";
export type Pattern = "stripes" | "checker" | "dots";

type Base = { at: [number, number] };

export type HookScene = Base & { type: "hook"; lines: string[]; lead: string; punch: string };
export type LogoScene = Base & { type: "logo"; name: string; tagline: string; pattern: Pattern };
export type FeatureScene = Base & {
  type: "feature";
  index: string;
  label: string;
  title: string;
  accent: string;
  subtitle: string;
  icon: IconName;
};
export type ListScene = Base & { type: "list"; title: string; accent: string; items: string[] };
export type StatScene = Base & { type: "stat"; value: number; suffix: string; label: string };
export type CtaScene = Base & { type: "cta"; name: string; tagline: string; accent: string; button: string; contact: string };

export type Scene = HookScene | LogoScene | FeatureScene | ListScene | StatScene | CtaScene;

export type PromoProps = {
  fps: number;
  width: number;
  height: number;
  duration: number;
  /** Seconds per beat; in-scene beats are timed against it so motion lands on the music. */
  beat: number;
  palette: Palette;
  scenes: Scene[];
};
