#!/usr/bin/env bash
# Wait for Postgres, apply migrations, then exec the given command.
set -euo pipefail

host="${POSTGRES_HOST:-postgres}"
port="${POSTGRES_PORT:-5432}"

echo "⏳ waiting for postgres at ${host}:${port} …"
for _ in $(seq 1 60); do
  if python -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${host}', ${port}))
except OSError:
    sys.exit(1)
" 2>/dev/null; then
    echo "✅ postgres is up"
    break
  fi
  sleep 1
done

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "⏫ applying migrations"
  alembic upgrade head
fi

exec "$@"
