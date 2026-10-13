# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# AutoSMM AI — single image used by the API, the Celery workers and the bot.
# Chromium ships in the image because the VisualAgent renders HTML cards.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Asia/Tashkent

WORKDIR /app

# Build-time only: psycopg/asyncpg wheels + fonts for the renderer.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
        fonts-dejavu-core \
        fonts-liberation \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# apt gives up on a slow link without saying so. On a link under ~200 KB/s the
# 9.7MB package index exceeds the default timeout, and apt reports it as `Ign:`
# — ignored, not failed — then carries on with no index at all. The very next
# `apt-get install` dies with "unable to locate package", which reads like a
# typo in the package list and sends you looking in the wrong place entirely.
#
# Placed here rather than beside the first apt block on purpose: above this
# line sit the cached pip layers, and a new step up there would invalidate them
# and re-download every wheel to fix a problem in the layer below.
RUN printf 'Acquire::Retries "8";\nAcquire::http::Timeout "180";\nAcquire::https::Timeout "180";\nAcquire::http::No-Cache "true";\n' \
    > /etc/apt/apt.conf.d/99-slow-link

# Chromium for the card renderer. `--with-deps` is deliberately NOT used: it
# resolves Ubuntu package names that do not exist on Debian slim, so the runtime
# libraries are installed explicitly instead.
#
# The download is 161MB and Playwright aborts it after 30s of silence, which a
# slow or lossy link reaches long before the file ends — it failed here at 30%.
# There is no resume: a timeout restarts from zero, so the connection timeout is
# raised to ten minutes *and* the whole install is retried, because one stall
# past the timeout otherwise costs the entire build.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
        libcups2 libdrm2 libxcb1 libxkbcommon0 libx11-6 libxcomposite1 libxdamage1 \
        libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
        libglib2.0-0 libexpat1 \
    && ( n=0; until PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=600000 playwright install chromium; do \
           n=$((n+1)); [ $n -ge 5 ] && echo "chromium: 5 urinish ham yiqildi" && exit 1; \
           echo "chromium: qayta urinish $n"; sleep 15; \
         done ) \
    && apt-get purge -y build-essential && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Emoji glyphs for the card renderer — captions and hooks carry emoji.
# ffmpeg powers the video service (branded motion clips for stories).
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-color-emoji \
        ffmpeg \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Install the shipped faces so Chromium can find them by family name. The card
# renderer uses `page.set_content`, which has no document origin — a file://
# @font-face is blocked there, and a CSS name that resolves to nothing falls
# silently through to DejaVu. Every card rendered before this was set in the
# wrong face and nothing said so.
RUN mkdir -p /usr/share/fonts/truetype/app \
    && cp app/assets/fonts/*.ttf /usr/share/fonts/truetype/app/ \
    && fc-cache -f >/dev/null

# Run as a non-root user; it must own the media directory it writes to.
RUN useradd --create-home --uid 10001 autosmm \
    && mkdir -p /app/media \
    && chown -R autosmm:autosmm /app /ms-playwright
USER autosmm

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
