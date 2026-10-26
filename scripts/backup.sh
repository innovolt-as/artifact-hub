#!/usr/bin/env bash
# Consistent backup of the hub's data: hub.db (via the SQLite backup API, never cp)
# plus the artifacts tree. Prints the archive path on stdout.
# Usage: [KEEP=14] scripts/backup.sh [DATA_DIR] [OUT_DIR]   (defaults: ./data and ./backups)
# Archives are owner-only; only the newest KEEP hub-*.tar.gz are kept (KEEP=0 keeps all). See docs/BACKUP.md.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA_DIR="${1:-./data}"
OUT_DIR="${2:-./backups}"
KEEP="${KEEP:-14}"  # newest hub-*.tar.gz archives to keep in OUT_DIR; 0 keeps all
umask 077  # archives hold all app data in plain text: owner only

[[ "$KEEP" =~ ^[0-9]+$ ]] || { echo "backup.sh: KEEP must be a whole number, got '$KEEP'" >&2; exit 1; }
command -v python3 >/dev/null || { echo "backup.sh: python3 is required" >&2; exit 1; }
[ -f "$DATA_DIR/hub.db" ] || { echo "backup.sh: $DATA_DIR/hub.db not found" >&2; exit 1; }

mkdir -p "$OUT_DIR"
OUT_DIR=$(cd "$OUT_DIR" && pwd)
archive="$OUT_DIR/hub-$(date +%Y%m%d-%H%M).tar.gz"
stage=$(mktemp -d)
# A failed run must leave nothing in OUT_DIR that looks like a backup.
trap 'rm -rf "$stage" "$archive.part"' EXIT

# Online-safe copy of the database, even while the hub is writing.
python3 -c '
import sqlite3, sys
src = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
' "$DATA_DIR/hub.db" "$stage/hub.db"

if [ -d "$DATA_DIR/artifacts" ]; then
  cp -R "$DATA_DIR/artifacts" "$stage/artifacts"
else
  mkdir "$stage/artifacts"
fi

tar -czf "$archive.part" -C "$stage" hub.db artifacts
mv "$archive.part" "$archive"

# Rotation: only archives this script names (hub-YYYYMMDD-HHMM.tar.gz), oldest first by name.
shopt -s nullglob
ours=("$OUT_DIR"/hub-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9].tar.gz)
if (( KEEP > 0 && ${#ours[@]} > KEEP )); then
  rm -f -- "${ours[@]:0:${#ours[@]}-KEEP}"
fi
echo "$archive"
