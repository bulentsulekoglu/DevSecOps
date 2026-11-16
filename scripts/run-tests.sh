#!/usr/bin/env bash
set -euo pipefail

# Geçici bir PostgreSQL konteyneriyle testleri çalıştırır (CI ve yerel kullanım aynı betiği kullanır).
cd "$(dirname "$0")/.."

SUFFIX="${GITHUB_RUN_ID:-local}-$$"
NET="testnet-$SUFFIX"
DB="testdb-$SUFFIX"

cleanup() {
  docker rm -f "$DB" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
docker run -d --rm --name "$DB" --network "$NET" --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test \
  postgres:16-alpine >/dev/null

ready=0
for _ in $(seq 1 90); do
  if docker logs "$DB" 2>&1 | grep 'ready for start up' >/dev/null \
     && docker exec "$DB" pg_isready -U test -d test -q; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || { echo "Test veritabanı hazır olmadı" >&2; exit 1; }

docker run --rm -u "$(id -u):$(id -g)" --network "$NET" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -e POSTGRES_HOST="$DB" -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test \
  -v "$PWD/app:/app" -w /app python:3.12-slim \
  sh -c "python -m venv /tmp/venv && /tmp/venv/bin/pip install -q -r requirements-dev.txt && /tmp/venv/bin/pytest -v -p no:cacheprovider"
