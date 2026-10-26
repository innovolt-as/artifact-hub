#!/usr/bin/env bash
# Run the test suite in the same Python as the app image (python:3.12-slim).
# Usage: scripts/test.sh [pytest args...]
set -euo pipefail
cd "$(dirname "$0")/.."

RUNTIME=$(command -v podman || command -v docker || true)
[ -n "$RUNTIME" ] || { echo "Needs podman or docker" >&2; exit 1; }

mkdir -p .pip-cache
exec "$RUNTIME" run --rm \
  -v "$PWD":/work -w /work \
  -v "$PWD/.pip-cache":/root/.cache/pip \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e UPDATE_GOLDEN="${UPDATE_GOLDEN:-}" \
  docker.io/library/python:3.12-slim \
  sh -c 'pip install -q --root-user-action=ignore --disable-pip-version-check -r requirements.txt -r requirements-dev.txt && python -m pytest -q -p no:cacheprovider "$@"' sh "$@"
