#!/usr/bin/env bash
# Run a release image against a copy of a backup, on a local port, to click through before upgrading.
# Usage: ADMIN_EMAIL=you@example.com [PORT=8001] [SITE_NAME=Rehearsal] scripts/rehearse.sh IMAGE BACKUP.tar.gz
# LOGIN_MODE (magic-link|password) is passed through from the environment.
# DRY_RUN=1 prints the container command instead of running it. Never touches ./data.
set -euo pipefail

[ $# -eq 2 ] || { echo "Usage: ADMIN_EMAIL=... $0 IMAGE BACKUP.tar.gz" >&2; exit 1; }
IMAGE=$1
ARCHIVE=$2
[ -n "${ADMIN_EMAIL:-}" ] || { echo "ADMIN_EMAIL is required" >&2; exit 1; }
[ -f "$ARCHIVE" ] || { echo "No such archive: $ARCHIVE" >&2; exit 1; }
PORT=${PORT:-8001}
SITE_NAME=${SITE_NAME:-Rehearsal}

RUNTIME=$(command -v docker || command -v podman || true)
[ -n "$RUNTIME" ] || { echo "Needs docker or podman" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar xzf "$ARCHIVE" -C "$tmp"
[ -f "$tmp/hub.db" ] || { echo "Archive has no hub.db: $ARCHIVE" >&2; exit 1; }

secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
tty_flags=""
[ -t 0 ] && tty_flags="-it"

cmd=("$RUNTIME" run --rm)
[ -n "$tty_flags" ] && cmd+=("$tty_flags")
cmd+=(-p "127.0.0.1:$PORT:8000" -v "$tmp:/data"
  -e "ADMIN_EMAILS=$ADMIN_EMAIL" -e "BASE_URL=http://localhost:$PORT"
  -e "LOGIN_MODE=${LOGIN_MODE:-magic-link}" -e "SECRET_KEY=$secret" -e SMTP_HOST= -e "SITE_NAME=$SITE_NAME" "$IMAGE")

echo "Open http://localhost:$PORT/login, enter $ADMIN_EMAIL; the login link is printed below." >&2

if [ "${DRY_RUN:-}" = 1 ]; then
  echo "${cmd[*]}"
  exit 0
fi

"${cmd[@]}"
