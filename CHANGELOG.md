# Changelog

## v1.0.0 (unreleased)

### Before you upgrade

- `DOMAIN` must be set in `.env` (e.g. `DOMAIN=apps.example.com`). The Caddyfile no longer has a hard-coded hostname and `docker compose` refuses to start `caddy` without it.
- `docker-compose.yml` now builds the image locally by default (`build: .`). If you run a published image, pin it in `docker-compose.override.yml` **before** updating the compose file, or `up` will start building instead of pulling.

See `docs/UPGRADING.md` for the step-by-step procedure. It is written in Norwegian for now.

### New

- `LOGIN_MODE=password`: log in with e-mail + password, no SMTP needed; admins set temporary passwords that must be changed on first login; `python -m app.passwd` CLI.
- Branding folder: `logo.svg`, `favicon-32.png` and `apple-touch-icon.png` in `data/branding/` replace the defaults.
- `app/mail.py`: a small e-mail contract (`configured()`, `send(to, subject, body) -> bool`) so other providers than SMTP can be added.
- `scripts/backup.sh` takes a consistent copy of `hub.db` and the artifacts; `scripts/rehearse.sh` runs a release against a backup copy before you upgrade.
- GitHub workflows: tests on every push and pull request; multi-arch image (`amd64`, `arm64`) published to GitHub Container Registry from `v*` tags.
- MIT license.
- Image tags are `vX.Y.Z` and `vX.Y`; `latest` only moves on release tags (not on pre-releases such as `v1.1.0-rc1`, nor on manual workflow runs).
- `.dockerignore` keeps `data/`, `backups/`, `.git/` and other local files out of the build context; `.gitignore` now also ignores `backups/` and `docker-compose.override.yml`.
