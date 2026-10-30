# Upgrading

The hub runs as a Docker image. Its data (`./data`: the apps and `hub.db`) lives outside the image and survives
upgrades.

## Running a published image

`docker-compose.yml` builds the image from the checkout. To run a released image instead, create
`docker-compose.override.yml` next to it (git ignores it):

```yaml
services:
  hub:
    image: ghcr.io/innovolt-as/artifact-hub:v1.4.1
    pull_policy: always
```

Images are tagged `vX.Y.Z` and `vX.Y`, and `latest` follows the newest release. Pin a full `vX.Y.Z`, so nothing
changes until you change the tag.

## Every upgrade

1. Take a backup on the server: `scripts/backup.sh` (needs `python3` on the host). It prints the path of the
   archive, which goes in `./backups/` by default. See [BACKUP.md](BACKUP.md).
2. Read "Before you upgrade" in [CHANGELOG.md](../CHANGELOG.md) for every version between yours and the new one.
3. Optional: rehearse on a copy. Fetch the archive with `scp` and run
   ```bash
   ADMIN_EMAIL=you@example.com scripts/rehearse.sh ghcr.io/innovolt-as/artifact-hub:vX.Y.Z hub-YYYYMMDD-HHMM.tar.gz
   ```
   This starts the new image on `localhost:8001` (`PORT` changes it) against an unpacked copy of the backup. It runs
   in the foreground: the login link is printed in the same terminal, and Ctrl-C stops it. Log in and click around.
4. Check out the new release: `git fetch --tags && git checkout vX.Y.Z`. This brings the compose file, Caddyfile
   and scripts that go with it. Check the result with `docker compose config --quiet`, which prints nothing when
   all is well. Leave out `--quiet` and it prints the whole configuration, secrets from `.env` included.
5. Start it:
   - published image: set the new tag in `docker-compose.override.yml`, then
     `docker compose pull && docker compose up -d`;
   - built from the checkout: `docker compose up -d --build`.
6. Open the front page, an app and `/admin`.

**Rolling back:** go back to the previous tag the same way and run the same commands. Usually only the image goes
back and `data/` is left alone, since new versions only ever add to the database. Restore the backup only if the
new version did change your data: see [Restoring](BACKUP.md#restoring).

## Switching login mode

From magic links to passwords:

1. Set `LOGIN_MODE=password` in `.env` and run `docker compose up -d`.
2. Give yourself a password: `docker compose exec hub python -m app.passwd set you@example.com`.
   `python -m app.passwd list` shows who has one.
3. Log in and give everyone else a temporary password under *People* on the admin page. They choose their own the
   first time they log in. `python -m app.passwd set <e-mail> --temporary` does the same from the command line.

People who are already logged in stay logged in until their login runs out (30 days). They have no password yet,
and need a temporary one from you before they can set their own.

Back to magic links: set `LOGIN_MODE=magic-link` and run `docker compose up -d`. The passwords stay in the database
and work again if you switch back.

To rehearse with passwords:
`LOGIN_MODE=password ADMIN_EMAIL=you@example.com scripts/rehearse.sh <image> <backup.tar.gz>`. A backup taken
before any passwords were set has none; the script prints the command that sets one in the rehearsal container.
