#!/usr/bin/env bash
# Local checks for scripts/backup.sh and scripts/rehearse.sh. Usage: tests/test_scripts.sh
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/data/artifacts/.versions/x" "$tmp/data/artifacts/.icons"
echo '<p>hi</p>' > "$tmp/data/artifacts/x.html"
python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('create table t(a)'); c.execute('insert into t values(1)'); c.commit()" "$tmp/data/hub.db"

out=$(scripts/backup.sh "$tmp/data" "$tmp/backups")
[[ "$out" == "$tmp"/backups/hub-*.tar.gz ]] || { echo "unexpected output: $out"; exit 1; }
tar tzf "$out" | grep -q '^hub.db$'
tar tzf "$out" | grep -q '^artifacts/x.html$'
tar tzf "$out" | grep -q '^artifacts/.versions/'
mkdir "$tmp/restore" && tar xzf "$out" -C "$tmp/restore"
[[ $(python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('select a from t').fetchone()[0])" "$tmp/restore/hub.db") == 1 ]]

if scripts/backup.sh "$tmp/nope" "$tmp/backups" 2>/dev/null; then echo "should fail without hub.db"; exit 1; fi
# A failing tar must not leave a partial archive (or .part file) behind.
mkdir "$tmp/faketar"
printf '#!/bin/sh\nprintf partial > "$2"\nexit 1\n' > "$tmp/faketar/tar"; chmod +x "$tmp/faketar/tar"
if PATH="$tmp/faketar:$PATH" scripts/backup.sh "$tmp/data" "$tmp/failout" 2>/dev/null; then echo "should fail when tar fails"; exit 1; fi
[[ -z $(ls -A "$tmp/failout") ]] || { echo "leftovers after failed tar: $(ls -A "$tmp/failout")"; exit 1; }

# Archives hold all app data in plain text: owner only.
mode() { python3 -c 'import os, sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$1"; }
[[ $(mode "$out") == 0o600 ]] || { echo "archive mode $(mode "$out"), want 0o600"; exit 1; }

# KEEP: only the newest KEEP archives named hub-YYYYMMDD-HHMM.tar.gz stay; other files are never touched.
rot="$tmp/rot"; mkdir "$rot"
for d in 20200101 20200102 20200103 20200104; do touch "$rot/hub-$d-0300.tar.gz"; done
touch "$rot/hub-manual-backup.tar.gz" "$rot/notes.txt" "$rot/backup.log"
new=$(KEEP=3 scripts/backup.sh "$tmp/data" "$rot")
left=$(cd "$rot" && ls | LC_ALL=C sort | tr '\n' ' ')
want="backup.log hub-20200103-0300.tar.gz hub-20200104-0300.tar.gz $(basename "$new") hub-manual-backup.tar.gz notes.txt "
[[ "$left" == "$want" ]] || { echo "KEEP=3 left: $left"; exit 1; }

# Default KEEP is 14; KEEP=0 keeps everything; a bad KEEP fails before writing anything.
many="$tmp/many"; mkdir "$many"
for i in $(seq -w 1 20); do touch "$many/hub-202001$i-0300.tar.gz"; done
scripts/backup.sh "$tmp/data" "$many" >/dev/null
[[ $(ls "$many" | wc -l | tr -d ' ') == 14 ]] || { echo "default KEEP left $(ls "$many" | wc -l) archives"; exit 1; }
for i in $(seq -w 1 20); do touch "$many/hub-201901$i-0300.tar.gz"; done
ls "$many" > "$tmp/before.txt"
new0=$(KEEP=0 scripts/backup.sh "$tmp/data" "$many")
want0=$(( $(wc -l < "$tmp/before.txt") + 1 ))
grep -qx "$(basename "$new0")" "$tmp/before.txt" && want0=$(( want0 - 1 ))   # same minute as the last run: overwritten
[[ $(ls "$many" | wc -l | tr -d ' ') == "$want0" ]] || { echo "KEEP=0 left $(ls "$many" | wc -l), want $want0"; exit 1; }
KEEP=08 scripts/backup.sh "$tmp/data" "$many" >/dev/null || { echo "KEEP=08 failed"; exit 1; }
[[ $(ls "$many" | wc -l | tr -d ' ') == 8 ]] || { echo "KEEP=08 left $(ls "$many" | wc -l) archives"; exit 1; }
mkdir "$tmp/badkeep"
for bad in abc 1234567; do
  if KEEP=$bad scripts/backup.sh "$tmp/data" "$tmp/badkeep" 2>/dev/null; then echo "should fail with KEEP=$bad"; exit 1; fi
done
[[ -z $(ls -A "$tmp/badkeep") ]] || { echo "a bad KEEP wrote: $(ls -A "$tmp/badkeep")"; exit 1; }

# The archive just written is never rotated away, even when the clock is behind older names.
future="$tmp/future"; mkdir "$future"
touch "$future/hub-29990101-0000.tar.gz"
fresh=$(KEEP=1 scripts/backup.sh "$tmp/data" "$future")
[[ -f "$fresh" ]] || { echo "KEEP=1 deleted the new archive"; exit 1; }
echo "backup.sh ok"

arch=$out
out=$(HUB_LANG=nb DRY_RUN=1 ADMIN_EMAIL=a@b.no PORT=8123 scripts/rehearse.sh ghcr.io/x/hub:v9 "$arch")
grep -q -- '-p 127.0.0.1:8123:8000' <<<"$out"
grep -q -- '-e ADMIN_EMAILS=a@b.no' <<<"$out"
grep -q -- '-e SMTP_HOST= ' <<<"$out"
grep -q -- 'ghcr.io/x/hub:v9' <<<"$out"
grep -q -- '-e LOGIN_MODE=magic-link' <<<"$out"
grep -q -- '-e HUB_LANG=nb' <<<"$out"
grep -q -- '--name hub-rehearsal-8123' <<<"$out"
pw=$(LOGIN_MODE=password DRY_RUN=1 ADMIN_EMAIL=a@b.no scripts/rehearse.sh img "$arch" 2>/dev/null)
grep -q -- '-e LOGIN_MODE=password' <<<"$pw"
grep -q -- "$tmp/data/hub.db" <<<"$out" && { echo "must not mount the real data dir"; exit 1; } || true
if ADMIN_EMAIL= DRY_RUN=1 scripts/rehearse.sh img x.tar.gz 2>/dev/null; then echo "should require ADMIN_EMAIL"; exit 1; fi
echo "rehearse.sh ok"
