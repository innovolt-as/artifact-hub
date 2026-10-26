# Apps on the hub

Any HTML page works on the hub as it is. This page covers how apps are stored, what they can use, and what the
hub adds to them. Read the [security model](../README.md#security-model) first: apps run with the visitor's login.

## Files

Apps live in `data/artifacts/`. The hub reads the folder on every request, so you can also `scp` or `rsync` files
straight in.

| File | |
|---|---|
| `name.html` | A single-file app, served at `/a/name/`. |
| `name/index.html` (and other files) | An app with several files, served at `/a/name/`. |
| `name.meta.json` or `name/meta.json` | Optional settings, see below. |
| `name.link.json` | A link card for an app that runs elsewhere: `{"title": "...", "url": "https://...", "admin_only": true}`. |
| `.icons/name.png` (or `.jpg`, `.webp`, `.gif`, `.svg`) | An icon uploaded on the admin page. |
| `.versions/name/` | Earlier versions, see below. |

`meta.json` can hold `title`, `description`, `emoji` (the icon when there is no uploaded image), `banner` (`false`
turns the banner off) and the access level: `"admin_only": true` for admins only, or `"access": "people"` with
`"people": ["a@example.com"]`. Without either, everyone who can log in sees the app. The admin page writes this
file for you, and it is kept when the app is replaced.

### Versions

Every time an app is replaced (from the admin page, `push.sh` or Claude), the old version is saved in
`data/artifacts/.versions/<name>/`, the last 10 per app. Single files are saved as `.html`, folder apps as `.zip`.
Versions are kept when an app is renamed or deleted.

There is no button to restore one. Copy the file back to `data/artifacts/<name>.html`, or unpack the `.zip` into
`data/artifacts/<name>/`.

## Storage: `window.claude.use("db")`

Artifacts made on claude.ai save data through `window.claude.use(...)`, which only exists there. The hub puts
`<script src="/static/hub.js">` first in `<head>` of every app page, and it provides a compatible version:

| Capability | On the hub |
|---|---|
| `db` | Stored in SQLite on the server, per app and per logged-in user. `collection`/`doc`, `get`/`set`/`update`/`delete`, `add`, `where`/`orderBy`/`limit`, and `onSnapshot`, which picks up changes from other tabs and devices every 5 seconds. |
| `downloads` | `save({filename, data})` becomes a normal browser download. |
| `user` | The logged-in e-mail address. `isOwner()` and `canEdit()` are true for admins. |
| Anything else (`sample`, `room`, `mcp`, …) | `null`. These need claude.ai. |

The data follows an app when it is renamed, and stays when the app is deleted, so it comes back if the app is
uploaded again. `GET /api/store/<name>` returns everything you have stored in one app as JSON.

## Storage: the key/value API

Apps written for the hub can use a plain key/value API instead. Every value belongs to one user and one app name,
and calls are ordinary same-origin `fetch` calls, so the login cookie comes along.

| Call | |
|---|---|
| `GET /api/me` | `{"email", "admin"}`, or 401 when not logged in. |
| `GET /api/data/<app>?prefix=logs/` | All keys for the app, optionally only those starting with a prefix. |
| `GET /api/data/<app>/<key>` | One value, or 404. |
| `PUT /api/data/<app>/<key>` | Stores a value. Body: `{"value": <json>}`. |
| `DELETE /api/data/<app>/<key>` | Deletes a value. |
| `POST /api/data/<app>/_batch` | `{"set": {key: value}, "delete": [keys]}` in one transaction, handy for imports. |

Writes need `Content-Type: application/json`. Limits: 512 KB per value, and 5000 keys and 25 MB per user per app.
Use the app's name (its slug) as `<app>`.

## A line on the front-page card

In the card view, an app can show one line of text under its name, such as a count or today's total. The app
writes it to the document `hub/summary`:

```js
const db = await window.claude.use("db");
await db.doc("hub/summary").set({ text: "12 open tasks" });
```

With the key/value API, write the key `hub/summary` with `{"value": {"text": "..."}}`. The line is per user, cut at
140 characters and shown as plain text.

## What the hub adds to every page

When the hub serves an HTML file from an app it adds:

- **`hub.js`**, first in `<head>`, for the storage above.
- **A banner** at the top: a dark strip with a back arrow, the hub's logo and the app's icon and name, linking to
  the front page. It scrolls away with the page and is left out when printing. It sits in its own shadow DOM, so
  the app's CSS and the banner's CSS do not affect each other. It only goes into pages the browser opens, not
  into HTML an app fetches with `fetch()` or shows in an iframe.
- **Pull to refresh** in the home-screen app, where iOS has none. It only starts when the page is scrolled to the
  top and you are not typing, and does nothing in a normal browser tab.
- **Two CSS rules** that keep the page from scrolling sideways on phones: `overflow-x: clip` on `html` and `body`,
  and at least 16px text in form fields on touch screens, so iOS does not zoom in and stay zoomed.

### Turning the banner off

The *banner* button on the admin page turns the banner off for one app (`"banner": false` in its meta). Turn it off
for apps with a fixed top bar (`position: fixed; top: 0`), which the banner covers until you scroll, and for apps
that do not scroll (`html, body { height: 100%; overflow: hidden }`), which lose their bottom edge.
