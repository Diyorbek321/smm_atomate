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

# Chromium for the card renderer. `--with-deps` is deliberately NOT used: it
# resolves Ubuntu package names that do not exist on Debian slim, so the runtime
# libraries are installed explicitly instead.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
        libcups2 libdrm2 libxcb1 libxkbcommon0 libx11-6 libxcomposite1 libxdamage1 \
        libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
        libglib2.0-0 libexpat1 \
    && playwright install chromium \
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

# Run as a non-root user; it must own the media directory it writes to.
RUN useradd --create-home --uid 10001 autosmm \
    && mkdir -p /app/media \
    && chown -R autosmm:autosmm /app /ms-playwright
USER autosmm

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
