# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Remotion render service. Build context is backend/ so the brand faces in
# app/assets/fonts ship with it:  docker build -f remotion/Dockerfile .
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim

ENV NODE_ENV=production PORT=3001 TZ=Asia/Tashkent

# Runtime libraries for Chrome Headless Shell (what Remotion renders with).
RUN printf 'Acquire::Retries "8";\nAcquire::http::Timeout "180";\n' > /etc/apt/apt.conf.d/99-slow-link \
    && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libgbm1 libasound2 \
        libxrandr2 libxkbcommon0 libxfixes3 libxcomposite1 libxdamage1 libpango-1.0-0 \
        libcairo2 libcups2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY remotion/package.json remotion/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

COPY remotion/ ./
COPY app/assets/fonts/Unbounded.ttf app/assets/fonts/Manrope.ttf public/fonts/

# Download the browser at build time, retried: a stall on a slow link otherwise
# costs the whole build, and at run time it would cost the first render.
RUN n=0; until npx remotion browser ensure; do \
      n=$((n+1)); [ $n -ge 5 ] && echo "chrome: 5 urinish ham yiqildi" && exit 1; \
      echo "chrome: qayta urinish $n"; sleep 15; \
    done

RUN useradd --create-home --uid 10002 remotion && chown -R remotion:remotion /srv
USER remotion

EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD node -e "fetch('http://localhost:3001/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.mjs"]
