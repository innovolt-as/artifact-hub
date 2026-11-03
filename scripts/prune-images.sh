#!/usr/bin/env bash
# Removes old hub images to free disk space on the server. Never removes the image a container uses (running or
# stopped), and keeps the newest KEEP of the others, so going back one version needs no download.
# Usage: [KEEP=1] [IMAGE=ghcr.io/innovolt-as/artifact-hub] [DOCKER=docker] scripts/prune-images.sh [--dry-run]
# --dry-run (-n) only prints what would be removed. See docs/UPGRADING.md.
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/innovolt-as/artifact-hub}"
KEEP="${KEEP:-1}"  # images besides the ones in use to keep, newest first; the previous version is there to go back to
DOCKER="${DOCKER:-docker}"
DRY=0
case "${1:-}" in
  "") ;;
  -n|--dry-run) DRY=1 ;;
  *) echo "Usage: [KEEP=1] scripts/prune-images.sh [--dry-run]" >&2; exit 1 ;;
esac

[[ "$KEEP" =~ ^[0-9]{1,6}$ ]] || { echo "prune-images.sh: KEEP must be a whole number up to 999999, got '$KEEP'" >&2; exit 1; }
KEEP=$((10#$KEEP))  # "08" is 8, not an invalid octal number
command -v "$DOCKER" >/dev/null || { echo "prune-images.sh: $DOCKER not found (set DOCKER=podman to use podman)" >&2; exit 1; }

# The images of every container, running or stopped: removing one would fail, or break a later start
in_use=""
ids=$("$DOCKER" ps -aq)
if [ -n "$ids" ]; then
  # shellcheck disable=SC2086  # one argument per container id
  in_use=$("$DOCKER" inspect --format '{{.Image}}' $ids)
fi

# The hub's images, newest first, one line per tag ("<none>" for an image that lost its tag to a newer pull)
listing=$("$DOCKER" images "$IMAGE" --no-trunc --format '{{.CreatedAt}}	{{.ID}}	{{.Tag}}' | LC_ALL=C sort -r)
[ -n "$listing" ] || { echo "No images named $IMAGE."; exit 0; }

kept=0
removed=0
seen=" "
while IFS=$'\t' read -r _ id _; do
  case "$seen" in *" $id "*) continue ;; esac  # vX.Y.Z, vX.Y and latest can be the same image
  seen="$seen$id "
  tags=$(awk -F'\t' -v id="$id" '$2 == id && $3 != "<none>" { print $3 }' <<< "$listing" | tr '\n' ' ')
  name="${tags:-${id#sha256:}}"
  name="${name% }"
  if grep -qxF "$id" <<< "$in_use"; then
    echo "keep  $name (in use)"
  elif [ "$kept" -lt "$KEEP" ]; then
    kept=$((kept + 1))
    echo "keep  $name"
  else
    echo "remove $name"
    removed=$((removed + 1))
    [ "$DRY" = 1 ] && continue
    if [ -n "$tags" ]; then
      for t in $tags; do "$DOCKER" rmi "$IMAGE:$t" >/dev/null </dev/null; done
    else
      "$DOCKER" rmi "$id" >/dev/null </dev/null
    fi
  fi
done <<< "$listing"

if [ "$DRY" = 1 ]; then echo "Dry run: $removed image(s) would be removed."; else echo "Removed $removed image(s)."; fi
