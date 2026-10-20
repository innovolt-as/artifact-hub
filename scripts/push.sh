#!/usr/bin/env bash
# Upload one or more artifacts to the hub from your own machine.
#   ./scripts/push.sh chart.html another.html my-app.zip
#   ./scripts/push.sh --private secret.html        (admin only)
#   ./scripts/push.sh --slug my-name --title "Pretty title" file.html
# Needs HUB_URL and HUB_TOKEN (= UPLOAD_TOKEN on the server), e.g. in ~/.config/artifact-hub.env
set -euo pipefail
[ -f "$HOME/.config/artifact-hub.env" ] && source "$HOME/.config/artifact-hub.env"
: "${HUB_URL:?set HUB_URL}" "${HUB_TOKEN:?set HUB_TOKEN}"

private=false; slug=""; title=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --private) private=true; shift ;;
    --slug) slug="$2"; shift 2 ;;
    --title) title="$2"; shift 2 ;;
    *) break ;;
  esac
done
[[ $# -gt 0 ]] || { echo "usage: push.sh [--private] [--slug name] [--title 'x'] file..." >&2; exit 1; }

for f in "$@"; do
  curl -fsS -X POST "$HUB_URL/api/upload" \
    -H "Authorization: Bearer $HUB_TOKEN" \
    -F "file=@$f" -F "admin_only=$private" \
    ${slug:+-F "slug=$slug"} ${title:+-F "title=$title"}
  echo
done
