# Artifact Hub

A small self-hosted home for the HTML pages and little apps you make with Claude. It puts them behind a login on
your own domain, lets you open them from your phone's home screen, and lets you share some of them with a few people.

Artifacts that save data with `window.claude.use("db")` keep working: the hub stores that data in SQLite, per user
or shared by everyone who can see the app.
A [Claude connector](docs/CONNECTOR.md) lets you publish and edit apps from a conversation in claude.ai, including
the mobile app.

It is one FastAPI process with SQLite and plain files, behind Caddy, meant for one person or a small group.

## What it does

- **Login** with a magic link by e-mail, or with a password if you would rather not set up SMTP.
- **A front page per user.** People pick the apps they want from the ones they can see; favourites and the most
  used come first. It works as a home-screen app on iOS and Android.
- **An admin page** (`/admin`): drag-and-drop upload of `.html` files or zipped folders, access per app, inviting
  people, titles and icons, and who used what in the last 7 days.
- **Uploads** from the browser, from the terminal (`scripts/push.sh`) or from Claude.
- **Versions.** The last 10 versions of every app are kept when it is replaced.
- **Shared data** for apps whose content is the same for everyone, such as a digest a scheduled Claude agent
  writes every morning. Each user still gets a private corner in it.
- **Link cards** for apps that run somewhere else, next to the hosted ones.
- **English or Norwegian** interface (`HUB_LANG`). Another language is one JSON file.

## Try it locally

```bash
docker run --rm -p 8000:8000 -e ADMIN_EMAILS=you@example.com ghcr.io/innovolt-as/artifact-hub
```

Open http://localhost:8000 and log in as `you@example.com`. Without SMTP the login link is printed in the
container's output. Drop an `.html` file on the *Upload* tab of `/admin` to publish it. Everything is gone when the container stops.

## Running it on a server

You need a server with Docker and Compose, a domain with an A record pointing at the server, and ports 80 and 443
open.

```bash
git clone https://github.com/innovolt-as/artifact-hub.git && cd artifact-hub
cp .env.example .env    # then fill it in, see below
docker compose up -d
```

Compose builds the image and runs it behind [Caddy](https://caddyserver.com), which gets and renews the HTTPS
certificate for `DOMAIN`. Everything worth keeping is in `./data` (the SQLite database and the apps); the
certificates are in the `caddy_data` volume.

To run a published image instead of building it, and for upgrades, see [docs/UPGRADING.md](docs/UPGRADING.md).
For backups, see [docs/BACKUP.md](docs/BACKUP.md).

### Configuration

All settings live in `.env`. [`.env.example`](.env.example) lists them with a comment each. These you have to set:

| Setting | |
|---|---|
| `DOMAIN`, `BASE_URL` | The hostname Caddy serves, and the public URL (`https://` + `DOMAIN`). |
| `SECRET_KEY` | Signs login cookies: `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| `ADMIN_EMAILS` | Who sees `/admin` and every app. |
| `SMTP_*` | Sends the magic links; any SMTP service works. With `SMTP_HOST` empty the links go to the log (`docker compose logs -f hub`). |

`UPLOAD_TOKEN` is only needed for `scripts/push.sh`. The hub will not start while `SECRET_KEY` or `UPLOAD_TOKEN`
still has the example value from `.env.example`.

To use your own logo and icons, put `logo.svg`, `favicon-32.png` and `apple-touch-icon.png` in `data/branding/`.

## Who can log in and see what

These people can log in:

- everyone in `ADMIN_EMAILS`;
- people invited under *People* on the admin page;
- addresses in `ALLOWED_EMAILS` and domains in `ALLOWED_DOMAINS`. `ALLOWED_DOMAINS=*` lets in anyone with an
  e-mail address.

Anyone else who asks for a link is told to check their e-mail, but nothing is sent, so the form does not reveal who
is on the list. A magic link works once, within 15 minutes, and a login lasts 30 days. There can be at most 3 open
links per address, and 10 sent per IP address per hour.

Each app has an access level, set on the admin page:

- **Everyone who can log in.**
- **Specific people.** Adding someone here also invites them.
- **Only me**, which means only admins. Apps published from Claude start here.

An app you are not allowed to see does not exist for you: it is in no list, and its address gives a 404. Removing
a person on the admin page takes them off every app.

### Password login

Set `LOGIN_MODE=password` to log in with e-mail and password instead. No SMTP is needed.

1. Give the first admin a password: `docker compose exec hub python -m app.passwd set you@example.com`.
2. Invite people on the admin page with a temporary password and pass it on yourself. They choose their own
   password the first time they log in.

Passwords need at least 10 characters. After 10 wrong passwords for an address within 15 minutes, or 30 from one IP
address within an hour, further attempts are refused. Setting a new password for someone lifts their block, and
`docker compose restart hub` clears all of them. Changing a password does not log out other devices. In password
mode `ALLOWED_DOMAINS=*` has no effect: only people with a password can log in.

## Publishing apps

**From the browser:** log in as an admin, open `/admin/upload` and drop `.html` files, or a `.zip` with an `index.html`.

**From the terminal**, with `UPLOAD_TOKEN` set on the server:

```bash
cat > ~/.config/artifact-hub.env <<EOF
HUB_URL=https://apps.example.com
HUB_TOKEN=<UPLOAD_TOKEN from the server's .env>
EOF

scripts/push.sh chart.html
scripts/push.sh --private notes.html          # only admins see it
scripts/push.sh --slug budget --title "Budget 2026" file.html
```

**From Claude:** add `https://<your domain>/mcp` as a custom connector in claude.ai, then ask Claude to put an
artifact in the hub. See [docs/CONNECTOR.md](docs/CONNECTOR.md).

An upload with the same name replaces the app and keeps its title, icon and access. You can also copy files
straight into `data/artifacts/`; the hub reads the folder on every request.

[docs/APPS.md](docs/APPS.md) covers the file layout, the storage APIs, the card line on the front page (recipe or `hub/summary`) and
what the hub adds to every page.

## Security model

Every app is served from the hub's own domain and runs with the visitor's login. That keeps apps simple (`fetch`
just works, no tokens), but it means:

- an app can read and change the visitor's data in **every** app on the hub, not just its own. The per-app split
  in the storage APIs keeps well-behaved apps apart; it does not stop a hostile one;
- an app opened by an admin can do anything that admin can, such as uploading apps, changing access and inviting
  people.

So only publish apps you trust. What does hold is the split between people: an app only ever sees the data of the
person using it, plus the [shared data](docs/APPS.md#shared-data) of apps that have it, which only admins can change.

Passwords, login links and connector tokens are stored as hashes. App data is stored as plain text. To report a
vulnerability, see [SECURITY.md](SECURITY.md).

## Development

```bash
scripts/test.sh          # the test suite in python:3.12-slim (podman or docker)
tests/test_scripts.sh    # the shell scripts
ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Artifact Hub is an independent project and is not affiliated with Anthropic.
