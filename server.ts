/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import express, { type Request, type Response } from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

/** Where the FastAPI backend lives. */
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
/** Injected server-side so the admin key never reaches the browser. */
const BACKEND_API_KEY = process.env.AUTOSMM_API_KEY ?? process.env.API_KEY ?? "";
const PORT = Number(process.env.PORT ?? 3000);

/** Paths forwarded verbatim to the backend. */
const PROXY_PREFIXES = ["/api/v1", "/media", "/health"];

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

async function proxyToBackend(req: Request, res: Response): Promise<void> {
  const target = `${BACKEND_URL}${req.originalUrl}`;
  const headers = new Headers();

  for (const [key, value] of Object.entries(req.headers)) {
    if (HOP_BY_HOP.has(key.toLowerCase())) continue;
    if (typeof value === "string") headers.set(key, value);
  }
  if (BACKEND_API_KEY) headers.set("x-api-key", BACKEND_API_KEY);

  const hasBody = !["GET", "HEAD"].includes(req.method);
  const body = hasBody && Buffer.isBuffer(req.body) && req.body.length ? req.body : undefined;

  try {
    const upstream = await fetch(target, { method: req.method, headers, body });

    res.status(upstream.status);
    upstream.headers.forEach((value, key) => {
      if (!HOP_BY_HOP.has(key.toLowerCase())) res.setHeader(key, value);
    });
    res.end(Buffer.from(await upstream.arrayBuffer()));
  } catch (error) {
    // The dashboard renders this as an offline banner rather than crashing.
    res.status(502).json({
      success: false,
      data: null,
      error: {
        code: "backend_unreachable",
        message: `Cannot reach the backend at ${BACKEND_URL}. Is it running?`,
        details: String(error),
      },
      meta: null,
    });
  }
}

async function startServer() {
  const app = express();

  // Raw body for proxied routes so the payload is forwarded untouched.
  app.use(PROXY_PREFIXES, express.raw({ type: "*/*", limit: "25mb" }), proxyToBackend);

  app.use(express.json());

  // Legacy direct-to-Gemini helper kept for ad-hoc experiments; the product
  // itself generates content through the backend agents.
  app.post("/api/ai/generate", async (req, res) => {
    try {
      const { prompt, systemInstruction } = req.body;
      const apiKey = process.env.GEMINI_API_KEY;

      if (!apiKey) {
        return res.status(500).json({ error: "GEMINI_API_KEY is not configured" });
      }

      const ai = new GoogleGenAI({
        apiKey,
        httpOptions: { headers: { "User-Agent": "aistudio-build" } },
      });

      const result = await ai.models.generateContent({
        model: process.env.GEMINI_MODEL ?? "gemini-1.5-flash",
        contents: prompt,
        config: { systemInstruction },
      });

      res.json({ text: result.text });
    } catch (error: any) {
      console.error("AI Generation Error:", error);
      res.status(500).json({ error: error.message || "Failed to generate content" });
    }
  });

  app.get("/api/dashboard/health", (_req, res) => {
    res.json({ status: "ok", backend: BACKEND_URL, keyConfigured: Boolean(BACKEND_API_KEY) });
  });

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({ server: { middlewareMode: true }, appType: "spa" });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Dashboard on http://localhost:${PORT}`);
    console.log(`Proxying ${PROXY_PREFIXES.join(", ")} → ${BACKEND_URL}`);
    if (!BACKEND_API_KEY) {
      console.warn("AUTOSMM_API_KEY is not set — the backend will reject requests in production mode.");
    }
  });
}

startServer();
