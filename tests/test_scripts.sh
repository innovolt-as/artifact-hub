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
echo "backup.sh ok"

arch=$out
out=$(DRY_RUN=1 ADMIN_EMAIL=a@b.no PORT=8123 scripts/rehearse.sh ghcr.io/x/hub:v9 "$arch")
grep -q -- '-p 127.0.0.1:8123:8000' <<<"$out"
grep -q -- '-e ADMIN_EMAILS=a@b.no' <<<"$out"
grep -q -- '-e SMTP_HOST= ' <<<"$out"
grep -q -- 'ghcr.io/x/hub:v9' <<<"$out"
grep -q -- '-e LOGIN_MODE=magic-link' <<<"$out"
grep -q -- '--name hub-rehearsal-8123' <<<"$out"
pw=$(LOGIN_MODE=password DRY_RUN=1 ADMIN_EMAIL=a@b.no scripts/rehearse.sh img "$arch" 2>/dev/null)
grep -q -- '-e LOGIN_MODE=password' <<<"$pw"
grep -q -- "$tmp/data/hub.db" <<<"$out" && { echo "must not mount the real data dir"; exit 1; } || true
if ADMIN_EMAIL= DRY_RUN=1 scripts/rehearse.sh img x.tar.gz 2>/dev/null; then echo "should require ADMIN_EMAIL"; exit 1; fi
echo "rehearse.sh ok"
