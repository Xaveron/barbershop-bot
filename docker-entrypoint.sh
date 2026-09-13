#!/bin/sh
set -e

echo "[entrypoint] applying database migrations..."
alembic upgrade head

if [ "${SEED_ON_START:-false}" = "true" ]; then
    echo "[entrypoint] seeding demo data..."
    python -m app.seed
fi

echo "[entrypoint] starting: $*"
exec "$@"
