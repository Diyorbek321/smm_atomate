// Structural checks on a render request. Copy quality is the Python side's job;
// this only refuses what would crash the renderer or run away with resources.

export const COMPOSITIONS = new Set(["BrandPromo"]);
export const SCENE_TYPES = new Set(["hook", "logo", "feature", "list", "stat", "cta"]);
export const MAX_SECONDS = 90;
export const MAX_SCENES = 16;
const HEX = /^#[0-9a-f]{6}$/i;
const PALETTE_KEYS = ["bg", "ink", "accent", "brand", "muted"];

// Fields each scene reads unguarded. A missing one would throw inside React and
// surface as a retryable 500; refusing it here makes it a 422 the caller won't retry.
const REQUIRED = {
  hook: { lines: "array", punch: "string" },
  logo: { name: "string", tagline: "string" },
  feature: { title: "string", label: "string", subtitle: "string", icon: "string" },
  list: { title: "string", items: "array" },
  stat: { value: "number", label: "string" },
  cta: { name: "string", tagline: "string", button: "string" },
};
const hasType = (value, kind) => (kind === "array" ? Array.isArray(value) : typeof value === kind);

/** Returns a list of problems; empty means the request may render. */
export function validateRequest(body) {
  const errors = [];
  if (!body || typeof body !== "object") return ["body must be a JSON object"];
  if (!COMPOSITIONS.has(body.composition)) errors.push(`unknown composition: ${body.composition}`);

  const p = body.props;
  if (!p || typeof p !== "object") return [...errors, "props must be an object"];
  if (![24, 25, 30, 60].includes(p.fps)) errors.push("fps must be 24, 25, 30 or 60");
  if (!(p.width > 0 && p.width <= 2160 && p.height > 0 && p.height <= 3840)) errors.push("width/height out of range");
  if (!(p.duration > 0 && p.duration <= MAX_SECONDS)) errors.push(`duration must be in (0, ${MAX_SECONDS}]`);
  if (!(p.beat > 0.2 && p.beat < 2)) errors.push("beat must be seconds per beat");
  for (const key of PALETTE_KEYS) {
    if (!HEX.test(p.palette?.[key] ?? "")) errors.push(`palette.${key} must be #rrggbb`);
  }

  if (!Array.isArray(p.scenes) || p.scenes.length === 0 || p.scenes.length > MAX_SCENES) {
    errors.push(`scenes must hold 1-${MAX_SCENES} items`);
    return errors;
  }
  let previousEnd = 0;
  p.scenes.forEach((scene, i) => {
    if (!SCENE_TYPES.has(scene?.type)) errors.push(`scenes[${i}].type unknown: ${scene?.type}`);
    for (const [key, kind] of Object.entries(REQUIRED[scene?.type] ?? {})) {
      if (!hasType(scene[key], kind)) errors.push(`scenes[${i}].${key} must be ${kind}`);
    }
    const [start, end] = Array.isArray(scene?.at) ? scene.at : [];
    if (!(typeof start === "number" && typeof end === "number" && end > start)) {
      errors.push(`scenes[${i}].at must be [start, end] with end > start`);
      return;
    }
    if (Math.abs(start - previousEnd) > 0.05) errors.push(`scenes[${i}] leaves a gap or overlap at ${start}s`);
    previousEnd = end;
  });
  if (errors.length === 0 && Math.abs(previousEnd - p.duration) > 0.05) errors.push("scenes do not end at duration");
  return errors;
}
