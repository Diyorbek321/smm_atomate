import assert from "node:assert/strict";
import { test } from "node:test";
import { validateRequest } from "../validate.mjs";

const palette = { bg: "#0B0B0C", ink: "#FFFFFF", accent: "#FFC400", brand: "#F5A800", muted: "#A3A3A8" };
const good = () => ({
  composition: "BrandPromo",
  props: {
    fps: 30, width: 1080, height: 1920, duration: 10, beat: 0.5, palette,
    scenes: [
      { type: "hook", at: [0, 6], lines: ["a"], lead: "", punch: "b" },
      { type: "cta", at: [6, 10], name: "x", tagline: "y", accent: "", button: "z", contact: "" },
    ],
  },
});

test("accepts a well-formed request", () => {
  assert.deepEqual(validateRequest(good()), []);
});

test("rejects unknown compositions and scene types", () => {
  const body = good();
  body.composition = "Nope";
  body.props.scenes[0].type = "explode";
  const errors = validateRequest(body);
  assert.ok(errors.some((e) => e.includes("unknown composition")));
  assert.ok(errors.some((e) => e.includes("type unknown")));
});

test("rejects gaps between scenes and a timeline that misses the duration", () => {
  const gap = good();
  gap.props.scenes[1].at = [7, 10];
  assert.ok(validateRequest(gap).some((e) => e.includes("gap")));

  const short = good();
  short.props.duration = 12;
  assert.ok(validateRequest(short).some((e) => e.includes("duration")));
});

test("rejects runaway durations and malformed colours", () => {
  const body = good();
  body.props.duration = 600;
  body.props.palette.accent = "yellow";
  const errors = validateRequest(body);
  assert.ok(errors.some((e) => e.startsWith("duration")));
  assert.ok(errors.some((e) => e.includes("palette.accent")));
});

test("rejects non-objects", () => {
  assert.deepEqual(validateRequest(null), ["body must be a JSON object"]);
});

test("rejects a scene missing a field its component reads", () => {
  const body = good();
  delete body.props.scenes[0].lines;
  body.props.scenes[1].button = 3;
  const errors = validateRequest(body);
  assert.ok(errors.includes("scenes[0].lines must be array"));
  assert.ok(errors.includes("scenes[1].button must be string"));
});

test("enforces fps, beat and scene-count limits", () => {
  const body = good();
  body.props.fps = 29;
  body.props.beat = 5;
  const errors = validateRequest(body);
  assert.ok(errors.some((e) => e.startsWith("fps")));
  assert.ok(errors.some((e) => e.startsWith("beat")));

  const many = good();
  many.props.scenes = Array.from({ length: 17 }, (_, i) => ({ type: "logo", at: [i, i + 1], name: "x", tagline: "y" }));
  assert.ok(validateRequest(many).some((e) => e.startsWith("scenes must hold")));
});
