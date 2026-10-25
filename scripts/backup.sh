#!/usr/bin/env bash
# Consistent backup of the hub's data: hub.db (via the SQLite backup API, never cp)
# plus the artifacts tree. Prints the archive path on stdout.
# Usage: scripts/backup.sh [DATA_DIR] [OUT_DIR]   (defaults: ./data and ./backups)
set -euo pipefail
cd "$(dirname "$0")/.."

DATA_DIR="${1:-./data}"
OUT_DIR="${2:-./backups}"

command -v python3 >/dev/null || { echo "backup.sh: python3 is required" >&2; exit 1; }
[ -f "$DATA_DIR/hub.db" ] || { echo "backup.sh: $DATA_DIR/hub.db not found" >&2; exit 1; }

mkdir -p "$OUT_DIR"
OUT_DIR=$(cd "$OUT_DIR" && pwd)
stage=$(mktemp -d); trap 'rm -rf "$stage"' EXIT

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

archive="$OUT_DIR/hub-$(date +%Y%m%d-%H%M).tar.gz"
tar -czf "$archive" -C "$stage" hub.db artifacts
echo "$archive"
