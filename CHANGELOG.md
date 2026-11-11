# Changelog

## v1.9.0 (unreleased)

### New

- Public sharing. An app can be switched on for it (*Public sharing* in its settings on the admin page, or
  `public_sharing` from Claude; it needs shared data). A user then makes a secret link to it, one per *share name* such
  as one per list, in the share sheet behind the new button in the banner, or under *Shared links* on the settings page.
  Anyone with the link opens the app without logging in, reads what the user put in `public/<name>/...` and
  leaves replies in `guests/<name>/...`, which they can delete again. A reply with a fixed id can be made by only one guest, so an app can let one person
  take an item. Guests are limited to 4096 bytes per reply, 500 replies per link and, per hour, 30 writes per IP
  address and 200 per link. The user can turn a link off, replace it, or clear the guests' replies. See
  [APPS.md](docs/APPS.md#public-sharing).
- `window.claude.use("share")`, the same for the owner and a guest on a public page, so one page can serve both.
- *Hide guests' replies from the owner* for apps that keep a surprise, and *Guests can read* for shared collections
  a guest may read one document at a time by id.
- An *agent zone*: with it on, an admin and a scheduled agent can read and write `data/users/<e-mail>/agent/...` for every
  user of the app, and `list_app_data` lists those paths. The rest of a user's branch stays private.
- The Claude connector knows about public sharing: `public_sharing`, `public_read`, `guests_hidden` and `agent_zone` in
  `create_app` and `update_app_info`, shown by `list_apps` and `get_app`, and a paragraph in its instructions. See
  [CONNECTOR.md](docs/CONNECTOR.md#public-sharing).
- A card recipe gets `user`, the viewer's e-mail address in lower case, to find their own branch in a shared app.

### Changed

- The settings of an app on the admin page are in four groups: *Who can open*, *Data*, *Public sharing* and *Display*.
- *Delete my data* also removes the user's secret links, their public and guest zones and the guest replies on their lists.
  Removing a person from the hub removes their links.

## v1.8.0 (2026-11-04)

### New

- `scripts/prune-images.sh` removes old hub images on the server to free disk space. It keeps the image in use and
  the newest other one, to go back to; `--dry-run` shows what it would remove. See
  [UPGRADING.md](docs/UPGRADING.md).
- A shared app can name collections that everyone with access may add to, but not change or delete: the *Everyone can
  add to* row in the app's settings on the admin page, or `append_collections` from Claude. The hub stamps each
  document with `_added_by` and `_added_at`, and an app checks `user.can("data.add:<name>")`. *Delete my data* also
  clears the `_added_by` mark on documents a user added. See
  [APPS.md](docs/APPS.md#collections-everyone-can-add-to).

### Fixed

- A row on the admin page shows the warning about personal data that Claude has written as a small icon, with the
  full text as a tooltip; it was a long line. The full text is still in the app's settings.
- The arrow on an app's row on the admin page looked like ↗ because it got the front page's chevron styling. It is
  one plain chevron again.

## v1.7.1 (2026-11-03)

### Changed

- Every section on the front page, *Favourites*, each group and *Other*, is a card of its own. Open, the apps are rows
  inside the card with a thin line between them; closed, the icons sit inside it.
- A closed section shows four icons to a row on a phone, a little larger than before, with the name on one line. A
  name too long for its icon ends in «…» instead of breaking in the middle of a word.
- The front page without a network shows its two sections as cards too.

## v1.7.0 (2026-11-02)

### Before you upgrade

- A hub left open as a home-screen app, or in a browser tab, still runs the old scripts against the new page. After
  upgrading, close the home-screen app and open it again once, and reload any open tab once. From this version on the
  front page reloads itself when it finds the hub has new scripts.
- No stored choice is changed: what was open or closed stays so, and the new open/closed choices for *Favourites* and
  *Other* are worked out from your old view until you tap one.

### New

- Every section on the front page, *Favourites*, each group and *Other*, is a list of cards when it is open and a
  row of icons with the name under each when it is closed. A tap on the heading switches, and the hub remembers it per
  section on your account. Tap an icon to open the app; hold it for the favourite menu, or hold and drag to reorder (the icons in *Other* are
  sorted by name and can't be moved).
- A *Groups* window, opened by *Groups* under the apps. It lists your groups with the number of apps in each. Make a
  group, rename it, delete it, or hold a row and drag to change the order of the groups.

### Changed

- The *list / icons* switch at the top of the front page is gone: the choice is now made per section.
- *Arrange apps* only places apps: tick what you want on the front page and choose a group for each app (the menu
  still has *New group …*). Renaming, deleting and making groups moved to *Groups*.
- Starting values on upgrade: if you used the list, every section starts open; if you used icons, *Favourites* and
  *Other* start closed. Groups keep their own open/closed choice from v1.6, so a group that was open (a grid of
  icons for the icon view) is now an open list.

## v1.6.1 (2026-11-02)

### Fixed

- After an upgrade, Safari could keep using the hub's old scripts for a while, so new buttons on the page did nothing
  (on the front page, *New group* in *Arrange apps*). Every script and the stylesheet now have an address that changes
  with their content, and the rest are checked with the server each time.

## v1.6.0 (2026-11-02)

### Before you upgrade

- A hub left open as a home-screen app keeps the old scripts until it is reloaded, so groups can look wrong offline
  until then. After upgrading, close the home-screen app and open it again once.

### New

- Everyone can make their own groups on the front page. *Arrange apps* (formerly *Choose apps*, opened by *＋ Add or remove apps*)
  is where you tick the apps you want, choose a group for each, and make, rename and delete groups. The front page shows
  *Favourites* first, then your groups in your order, then *Other* with the apps that are in no group (*All apps* while
  you have no groups). A group folds up and opens again when you tap its heading or its row of icons, and the hub
  remembers it on your account. Hold an app and drag it to reorder inside favourites or a group; hold a heading to
  move the group. Groups are yours alone: other people do not see them. Deleting a group sends its apps to *Other*.
  You can have up to 30 groups.

### Changed

- *Most used* is gone from the front page, replaced by groups. An app you have put in favourites shows only there, not
  also in its group. The offline front page from v1.5.0 looks and works as before.
- The sheet no longer lists new apps first: a new app sits under *No group* in alphabetical order, and is still marked
  *New*.

### Fixed

- The front page now also switches to the offline view when it is already open and the connection goes, which is how
  you usually come back to the hub on a phone. It switches at once when the phone is offline, and after about 3 seconds
  when the server does not answer; it goes back to the normal page by itself when the server answers.

## v1.5.0 (2026-11-02)

### Before you upgrade

- Going back to an earlier version afterwards needs one extra step, since phones keep the new service worker: see
  "Going back to a version before v1.5.0" in [docs/UPGRADING.md](docs/UPGRADING.md).

### New

- Apps can work offline. Turn on *Works offline* in an app's settings on the admin page and the hub stores the app on
  the phone, so it opens without a connection. The front page is stored too, and shows which apps open offline. Only
  the page and its files are stored, not data, and apps behind a code lock never are. See "Offline" in
  [docs/APPS.md](docs/APPS.md) and "Offline copies" in the README.
- `create_app` and `update_app_info` in the connector take an `offline` parameter for the same switch.
- The hub as a home-screen app goes back to the front page after two minutes away. It stays on the app while you have
  typed something that is not saved, or while the app asks to with `window.hubStay(true)`.

### Fixed

- A white flash before the stylesheet loads, and when an app locks.

## v1.4.1 (2026-10-30)

### New

- *Delete my data* on the settings page removes everything you have stored in all apps. Shared data, your settings
  and your code lock stay. It asks for your code, or for a typed word if you have no code.

### Changed

- The top bar has the front page's dark colour on every page.
- *Log out* has moved from the top bar to the settings page.

### Fixed

- On an iPhone, the settings sheet on the admin page and the list of apps on the front page opened as a sliver at the
  bottom of the screen, or not at all.
- The stylesheet's address now changes with its content, so a browser picks up a new version after an upgrade.
- On older phones the switches show when they are off, and the code screen sends the form at the fourth digit.

## v1.4.0 (2026-10-30)

### New

- The admin page has tabs, each with its own address: *Apps* (`/admin`), *Upload* (`/admin/upload`), *People*
  (`/admin/people`) and *Statistics* (`/admin/stats`).
- The *Apps* tab is a search box and one short row per app. Tapping a row opens a settings sheet with the name and
  icon, access, the *Shared data* and *Banner at the top* switches and *Delete app*.
- A settings page at `/settings` for everyone who is logged in, reached through the e-mail address in the top bar
  (a small person icon on phones). *Appearance* is *Automatic*, *Light* or *Dark*, and applies to the hub's own pages
  only, not to apps, the banner or the login page.
- A code lock per app. Choose a four-digit code in the *Code lock* section of the settings page and switch on the apps
  that should ask for it, so someone who borrows your logged-in phone cannot open them. The connector still reaches
  locked apps. See "Security model" in the README.
- `python -m app.applock reset <e-mail>` gives someone who has forgotten their code a one-time code, and
  `python -m app.applock list` shows who has a code and how many apps they have locked.

### Changed

- *Change password* has moved from the top bar to the settings page. It only shows when `LOGIN_MODE=password`.
- The *Apps* and *Upload* tabs no longer reload the page when an app changes.

## v1.3.0 (2026-10-30)

### Before you upgrade

- The banner in apps now stays fixed at the top, so it covers an app's own sticky or fixed top bar. Give such a bar
  `top: var(--hub-banner-h, <its current value>)` before upgrading: older versions never set the variable, so the
  change does nothing until then. Or turn the banner off for that app on the admin page. Turn it off for apps that
  are exactly one screen tall (`100dvh`) too. See "A top bar under the banner" in `docs/APPS.md`.

### New

- Card recipes: an app can put a `<script data-hub-card>` in its page that turns its data into the line on its
  front-page card. The hub runs it on the server in a separate, killable process with a short deadline. See
  "A line on the front-page card" in `docs/APPS.md`.
- The front page refreshes in place when you come back to it, and blinks the cards whose line changed.
- Pull to refresh moves the content with your finger, keeps the header still and glows green when it is done.
- A sticky top row on the front page.
- Hold and drag a favourite to change the order. The order is saved.
- The connector's `get_app` returns a `card` field: the line the app's card recipe gives right now, or the recipe's
  error, so Claude can check a recipe right after writing it.

### Changed

- The star, the view switch and "Choose apps" no longer reload the page.
- The front page no longer reloads by itself after 5 minutes.
- The banner in apps now always stays fixed at the top, and links to anchors in an app stop under it.
- Card recipes run in V8 through `mini-racer` 0.14.1, so the image gets bigger (about 22 MB compressed).

## v1.2.0 (2026-10-27)

### New

- Shared data in apps (`"data": "shared"` in an app's meta, the *data* button on the admin page): everyone who can
  see the app reads its documents, only admins change them, and each user's `data/users/<e-mail>/` branch stays
  private, as with artifacts on claude.ai. Turning it on can copy your current documents into the shared data.
  See "Shared data" in `docs/APPS.md`.
- The front-page line of an app with shared data comes from the shared `hub/summary` document.
- The connector: `create_app` and `update_app_info` take `shared_data`, `update_app_info` also `copy_my_data`,
  and `list_apps` shows each app's data setting. Claude asks whether an app's content is shared or personal before
  it creates an app that it or a scheduled agent will fill.
- The admin page warns about an app that is shared with others but has personal data Claude wrote in the last 30
  days, since only the admin sees that content. The access dialog and the connector give the same warning when
  such an app is shared.

Existing apps keep personal data and behave as before.

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
