#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
exec uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8781}"
