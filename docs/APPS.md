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
turns the banner off), `data` (`"shared"` for [shared data](#shared-data)) and the access level: `"admin_only": true` for admins only, or `"access": "people"` with
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
| `db` | Stored in SQLite on the server, per app and per logged-in user, or [shared](#shared-data). `collection`/`doc`, `get`/`set`/`update`/`delete`, `add`, `where`/`orderBy`/`limit`, and `onSnapshot`, which picks up changes from other tabs and devices every 5 seconds. |
| `downloads` | `save({filename, data})` becomes a normal browser download. |
| `user` | The logged-in e-mail address, also as `id()`. `isOwner()` and `canEdit()` are true for admins; `can("data.write")` says whether the user may change shared data. |
| Anything else (`sample`, `room`, `mcp`, …) | `null`. These need claude.ai. |

The data follows an app when it is renamed, and stays when the app is deleted, so it comes back if the app is
uploaded again. `GET /api/store/<name>` returns everything you can read in one app as JSON.

## Shared data

By default everything an app stores with `window.claude.use("db")` belongs to the person using it. That does not
fit an app whose content is the same for everyone, such as a news digest that a scheduled Claude agent writes every
morning: the agent writes as one person, and nobody else would see it.

Such an app can have shared data instead: the *Shared data* switch in an app's settings on the admin page, `"data": "shared"` in its meta, or
`shared_data` from [Claude](CONNECTOR.md). Then it works like an artifact on claude.ai:

- every document is shared by everyone who can see the app;
- only admins change shared documents. For anyone else `set`, `update` and `delete` reject with
  `invalid_argument`;
- each user's own branch, `data/users/<e-mail>/...`, stays private to that user, admins included. Use it for
  anything personal, for example `db.collection("data/users/" + await user.id()).doc("settings")`, with
  `user = await window.claude.use("user")`. Someone
  else's branch reads as empty.

Turning shared data on asks whether to copy your current documents in the app into the shared data, where
everyone with access sees them, or to start empty. Other users' personal documents are hidden while shared data
is on. Nothing is deleted: turn it off and the personal data is back. The key/value API below is always per user.

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

In the card view, an app can show one line of text under its name, such as a count or today's total. The best way
is a card recipe: a `<script data-hub-card>` block in the app's HTML with a function `hubCard` that computes the
line from the data the app has stored. The hub runs it every time the front page is shown, so the line is always
current and the app does not have to be opened to update it:

```html
<script data-hub-card>
async function hubCard({ db, today }) {
  const day = await db.doc(`days/${today}`).get();
  return day.exists ? `${day.data().kcal} kcal today` : null;
}
</script>
```

`hubCard` gets `{ db, today, now, timeZone }` and returns a string, or `null` for no line (it may be `async`).

- `db` is read-only: `db.doc(path).get()`, `db.collection(path).get()`, and `.where(field, op, value)`,
  `.orderBy(field, dir)` and `.limit(n)` on a collection (a collection read sees at most the 500 documents with the
  highest ids). It reads what the viewer sees in the app: personal data, or in an app with shared data the shared
  documents and the viewer's own branch.
- `today` is the viewer's date as `YYYY-MM-DD`, `now` the time in milliseconds and `timeZone` the viewer's IANA zone
  (the hub learns it from the browser; until then it is the server's).
- No DOM and no network, only plain functions. The recipe has 0.25 seconds for everything it does and 32 MB of memory;
  one that takes longer, or throws, fails (see below for what the card then shows).
- The first `<script data-hub-card>` in the page counts. The line is trimmed and cut at 140 characters and shown as
  plain text. Claude can see what it gives with `get_app`: the `card` field is `{"text": ...}` with the line (or
  `null` for none), or `{"error": ...}` with one of the codes below.

The recipe reads in rounds. It only sees the data the hub has handed it, and a read of anything else ends the round:
the hub reads every path that round asked for and runs the recipe again from the start, now with that data. There
are at most 5 rounds and 50 paths per round. So read in parallel with `Promise.all`, or read a whole collection with
`where`/`orderBy`/`limit`, rather than one document at a time in a loop with `await`: a loop over the seven days of a
week takes a round per day and fails with `too_many_reads`, although the same loop works in the app.

```js
// week: an array of dates as YYYY-MM-DD
const days = await Promise.all(week.map((d) => db.doc(`days/${d}`).get()));
```

| Error | |
|---|---|
| `timeout` | The recipe took more than 0.25 seconds, reads included. |
| `memory` | It used more than 32 MB. |
| `no_function` | The block defines no `hubCard` function. |
| `not_text` | It returned something other than a string or `null`. |
| `too_many_reads` | It needed more than 5 rounds, or more than 50 paths in one round. |
| `bad_path` | It asked for a path the hub cannot read. |
| `failed: <message>` | A syntax error or an exception, with its first line. `failed: worker` means the hub could not run recipes at all. |

What wins: the recipe, when the app has one. If it fails, the card shows the stored `hub/summary` line only if it was
written today in the viewer's time zone; an older one would be stale, so the card then has no line.

For a line that cannot be computed from stored data, the app writes it to the document `hub/summary` instead:

```js
const db = await window.claude.use("db");
await db.doc("hub/summary").set({ text: "12 open tasks" });
```

With the key/value API, write the key `hub/summary` with `{"value": {"text": "..."}}`. This line is per user, cut at
140 characters and shown as plain text. In an app with shared data it is the shared `hub/summary` document, the
same for everyone.

## What the hub adds to every page

When the hub serves an HTML file from an app it adds:

- **`hub.js`**, first in `<head>`, for the storage above.
- **A banner** at the top: a dark strip with a back arrow, the hub's logo and the app's icon and name, linking to
  the front page. It stays fixed at the top while the page scrolls (an empty placeholder of the same height keeps the content below
  it) and is left out when printing. Its height is available as the CSS variable `--hub-banner-h` (see
  [below](#a-top-bar-under-the-banner)), and links to anchors and `scrollIntoView` stop under it. It sits in its own shadow DOM, so
  the app's CSS and the banner's CSS do not affect each other. It only goes into pages the browser opens, not
  into HTML an app fetches with `fetch()` or shows in an iframe.
- **Pull to refresh** in the home-screen app, where iOS has none. It only starts when the page is scrolled to the
  top and you are not typing, and does nothing in a normal browser tab. It moves the direct children of `<body>`
  with the finger, except those that are `position: fixed`: a fixed tab bar that is a direct child of `<body>` stays
  put, while a fixed element nested inside another element moves along until the pull is over.
- **Two CSS rules** that keep the page from scrolling sideways on phones: `overflow-x: clip` on `html` and `body`,
  and at least 16px text in form fields on touch screens, so iOS does not zoom in and stay zoomed.

### A top bar under the banner

The banner is fixed at the top of the screen, so an app's own sticky or fixed top bar (`position: sticky` or
`position: fixed` with `top: 0`) would end up under it. Place the bar right below the banner with
`top: var(--hub-banner-h, 0px)`, or `top: var(--hub-banner-h, <its current value>)` to keep a value of its own. The
variable is only set while the banner is there, and follows its height (safe area included) when the screen turns.

### Turning the banner off

The *Banner at the top* switch in an app's settings on the admin page turns the banner off for one app (`"banner": false` in its meta). Turn it off
for apps that are exactly one screen tall (`100dvh`): with the banner they no longer fit, and a strip of them is
always out of sight. Turn it off as well for an app whose top bar cannot be moved as above.
