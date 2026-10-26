# Changelog

## v1.1.1 (2026-10-26)

### Before you upgrade

- The hub no longer starts while `SECRET_KEY` or `UPLOAD_TOKEN` still has the example value from `.env.example` (anything starting with `change-me`). Set both to long random strings first, for example with `python3 -c "import secrets; print(secrets.token_hex(32))"`. A new `SECRET_KEY` logs everyone out.

### Changed

- The upload token is compared in constant time.
- The hub logs a warning at startup when `SECRET_KEY` is not set. It then uses a random key, so everyone is logged out at every restart.
- `.env.example` leaves `UPLOAD_TOKEN` empty, which turns token uploads off.
- `requirements.txt` pins every dependency, generated from `requirements.in`, so an image built from a tag always gets the same packages.
- CI runs `ruff check .`.
- The README and `docs/UPGRADING.md` are in English. The README describes the security model; details on apps and the Claude connector moved to `docs/APPS.md` and `docs/CONNECTOR.md`.

### Removed

- `scripts/build-and-push.sh`. Release images are built by the `build` workflow from `v*` tags.

## v1.1.0 (2026-10-26)

### Before you upgrade

- The default language is now English. Set `HUB_LANG=nb` in `.env` to keep the Norwegian interface. An unknown `HUB_LANG` stops the hub at startup.
- `mail.send` now takes `html`, `images` and `sender_name` too. A custom mail provider with the old 3-argument `send(to, subject, text)` raises `TypeError`: the user sees "check your e-mail" and nothing arrives. Update it before upgrading.
- `scripts/backup.sh` now keeps only the newest 14 `hub-YYYYMMDD-HHMM.tar.gz` archives in its output folder and deletes older ones after each run. Move archives you want to keep, or run it with `KEEP=0`.

### New

- `HUB_LANG` and `app/lang/`: all user-visible text lives in language files (`en.json`, `nb.json`). See "Adding a language" in `CONTRIBUTING.md`.
- HTML login e-mail with the hub icon.
- `SITE_NAME` is used as the sender name when `SMTP_FROM` is only an address.
- `scripts/backup.sh` writes owner-only archives and keeps the newest `KEEP` (default 14). `docs/BACKUP.md` covers nightly backups with cron, what a backup contains, the weakness of keeping it on the same server, and how to keep an encrypted copy elsewhere.

### Changed

- `mail.send(to, subject, text, html=None, images=None, sender_name=None)`. Custom providers must accept the new arguments.

## v1.0.0 (2026-10-26)

### Before you upgrade

- `DOMAIN` must be set in `.env` (e.g. `DOMAIN=apps.example.com`). The Caddyfile no longer has a hard-coded hostname and `docker compose` refuses to start `caddy` without it.
- `docker-compose.yml` now builds the image locally by default (`build: .`). If you run a published image, pin it in `docker-compose.override.yml` **before** updating the compose file, or `up` will start building instead of pulling.

### New

- `LOGIN_MODE=password`: log in with e-mail + password, no SMTP needed; admins set temporary passwords that must be changed on first login; `python -m app.passwd` CLI; lockout limits documented.
- Branding folder: `logo.svg`, `favicon-32.png` and `apple-touch-icon.png` in `data/branding/` replace the defaults.
- `app/mail.py`: a small e-mail contract (`configured()`, `send(to, subject, body) -> bool`) so other providers than SMTP can be added.
- `scripts/backup.sh` takes a consistent copy of `hub.db` and the artifacts; `scripts/rehearse.sh` runs a release against a backup copy before you upgrade.
- GitHub workflows: tests on every push and pull request; multi-arch image (`amd64`, `arm64`) published to GitHub Container Registry from `v*` tags.
- MIT license.
- Image tags are `vX.Y.Z` and `vX.Y`; `latest` only moves on release tags (not on pre-releases such as `v1.1.0-rc1`, nor on manual workflow runs).
- `.dockerignore` keeps `data/`, `backups/`, `.git/` and other local files out of the build context; `.gitignore` now also ignores `backups/` and `docker-compose.override.yml`.
