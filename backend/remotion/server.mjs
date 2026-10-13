// Remotion render service. POST /render {composition, props} -> video/mp4 (muted).
// The picture only: the Python side lays the tempo-locked bed and SFX under it,
// so every engine in AutoSMM shares one sound and one delivery encode.
import { mkdtemp, readFile, rm } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { ensureBrowser, renderMedia, selectComposition } from "@remotion/renderer";
import { validateRequest } from "./validate.mjs";

const PORT = Number(process.env.PORT ?? 3001);
const MAX_BODY = 512 * 1024;
const TIMEOUT_MS = Number(process.env.REMOTION_RENDER_TIMEOUT_MS ?? 600_000);
const CONCURRENCY = process.env.REMOTION_CONCURRENCY ? Number(process.env.REMOTION_CONCURRENCY) : null;
const here = path.dirname(fileURLToPath(import.meta.url));

const log = (event, fields = {}) => console.log(JSON.stringify({ ts: new Date().toISOString(), event, ...fields }));

let serveUrl = null;
// One render at a time: a Chromium render peaks near a gigabyte, and the
// failure mode of two at once is an OOM kill, not a slow queue.
let queue = Promise.resolve();

async function prepare() {
  await ensureBrowser();
  serveUrl = await bundle({ entryPoint: path.join(here, "src/index.ts"), publicDir: path.join(here, "public") });
  log("bundle_ready", { serveUrl });
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(Object.assign(new Error("body too large"), { status: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(Object.assign(new Error("invalid JSON"), { status: 400 }));
      }
    });
    req.on("error", reject);
  });
}

async function render({ composition, props }) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "remotion-"));
  const out = path.join(dir, "out.mp4");
  try {
    const comp = await selectComposition({ serveUrl, id: composition, inputProps: props });
    await renderMedia({
      serveUrl,
      composition: comp,
      inputProps: props,
      codec: "h264",
      crf: 16,
      muted: true,
      outputLocation: out,
      timeoutInMilliseconds: TIMEOUT_MS,
      ...(CONCURRENCY ? { concurrency: CONCURRENCY } : {}),
    });
    return { data: await readFile(out), frames: comp.durationInFrames, fps: comp.fps };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function send(res, status, body, headers = {}) {
  const payload = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
  res.writeHead(status, { "content-type": Buffer.isBuffer(body) ? "video/mp4" : "application/json", "content-length": payload.length, ...headers });
  res.end(payload);
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    return send(res, serveUrl ? 200 : 503, { ok: Boolean(serveUrl) });
  }
  if (req.method !== "POST" || req.url !== "/render") return send(res, 404, { error: "not found" });
  if (!serveUrl) return send(res, 503, { error: "bundle not ready" });

  let body;
  try {
    body = await readJson(req);
  } catch (err) {
    return send(res, err.status ?? 400, { error: err.message });
  }
  const errors = validateRequest(body);
  if (errors.length) return send(res, 422, { error: "invalid request", details: errors });

  const started = Date.now();
  const job = queue.then(() => render(body));
  queue = job.catch(() => undefined);
  try {
    const { data, frames, fps } = await job;
    log("rendered", { composition: body.composition, frames, ms: Date.now() - started, bytes: data.length });
    return send(res, 200, data, { "x-frames": String(frames), "x-fps": String(fps) });
  } catch (err) {
    log("render_failed", { error: String(err?.message ?? err).slice(0, 500) });
    return send(res, 500, { error: "render failed", detail: String(err?.message ?? err).slice(0, 300) });
  }
});

prepare()
  .then(() => server.listen(PORT, () => log("listening", { port: PORT })))
  .catch((err) => {
    log("startup_failed", { error: String(err?.message ?? err) });
    process.exit(1);
  });
