#!/usr/bin/env bash
# Ship the current commit to the VPS: build here, load there, restart.
#
#   backend/deploy/deploy.sh            # images + dashboard
#   SKIP_IMAGES=1 backend/deploy/deploy.sh   # dashboard only
#
# Images are built on this machine on purpose: the VPS also serves production
# sites, and a build there competes with them for memory.
set -euo pipefail

HOST="${DEPLOY_HOST:-root@164.90.223.92}"
DIR="${DEPLOY_DIR:-/opt/autosmm}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"

if [[ -z "${SKIP_IMAGES:-}" ]]; then
  echo "==> images autosmm-*:$TAG"
  docker build -q -t "autosmm-app:$TAG" "$ROOT/backend"
  docker build -q -f "$ROOT/backend/remotion/Dockerfile" -t "autosmm-remotion:$TAG" "$ROOT/backend"
  docker save "autosmm-app:$TAG" "autosmm-remotion:$TAG" | gzip -1 | ssh "$HOST" 'gunzip | docker load'
fi

echo "==> dashboard"
(cd "$ROOT" && npm run build >/dev/null)
ssh "$HOST" "mkdir -p $DIR/dashboard"
rsync -az --delete "$ROOT/dist" "$ROOT/package.json" "$ROOT/package-lock.json" "$HOST:$DIR/dashboard/"
rsync -az "$ROOT/backend/deploy/docker-compose.prod.yml" "$HOST:$DIR/docker-compose.yml"

echo "==> restart"
ssh "$HOST" bash -s <<EOF
set -euo pipefail
cd $DIR
sed -i "s/^TAG=.*/TAG=$TAG/" .env
docker compose up -d --remove-orphans
cd dashboard && npm ci --no-audit --no-fund >/dev/null
pm2 startOrReload ecosystem.config.cjs --update-env && pm2 save >/dev/null
docker compose -f $DIR/docker-compose.yml ps --format '{{.Name}}\t{{.Status}}'
EOF
echo "==> deployed $TAG"
