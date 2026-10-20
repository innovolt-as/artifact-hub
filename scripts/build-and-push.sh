#!/usr/bin/env bash
# Build the image locally and push to GitHub Container Registry.
#   GHCR_IMAGE=ghcr.io/<user>/artifact-hub ./scripts/build-and-push.sh [tag]
# Uses podman if available, otherwise docker (override with CONTAINER_CLI=docker).
set -euo pipefail
IMAGE="${GHCR_IMAGE:?set GHCR_IMAGE=ghcr.io/<user>/artifact-hub}"
TAG="${1:-latest}"
CLI="${CONTAINER_CLI:-$(command -v podman >/dev/null && echo podman || echo docker)}"
# --platform: build for a typical x86 VPS even on an Apple Silicon Mac
# --format docker: podman defaults to OCI; docker-format manifest keeps HEALTHCHECK working on the VPS
FORMAT=(); [ "$CLI" = podman ] && FORMAT=(--format docker)
"$CLI" build --platform linux/amd64 "${FORMAT[@]}" -t "$IMAGE:$TAG" "$(dirname "$0")/.."
"$CLI" push "$IMAGE:$TAG"
echo "Pushed $IMAGE:$TAG — on the server: docker compose pull && docker compose up -d"
