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
turns the banner off), `data` (`"shared"` for [shared data](#shared-data)), the settings for
[public sharing](#public-sharing) (`public`, `public_read`, `guests_hidden`, `agent`) and the access level: `"admin_only": true` for admins only, or `"access": "people"` with
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
| `user` | The logged-in e-mail address, also as `id()`. `isOwner()` and `canEdit()` are true for admins; `can("data.write")` says whether the user may change shared data, and `can("data.add:<collection>")` whether they may [add to a collection](#collections-everyone-can-add-to). |
| `share` | Only in an app with [public sharing](#public-sharing), for its owner and on its public page; `null` elsewhere. `share.db` reaches the `public/` and `guests/` zones for one share name. |
| Anything else (`sample`, `room`, `mcp`, …) | `null`. These need claude.ai. |

The data follows an app when it is renamed, and stays when the app is deleted, so it comes back if the app is
uploaded again. The exceptions are the app's [secret links](#the-link) and guest replies, which are deleted with it. `GET /api/store/<name>` returns everything you can read in one app as JSON.

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

### Collections everyone can add to

Sometimes people who can only read should still be able to put something in, such as a question for a scheduled
agent to answer. A shared app can name top-level collections that everyone with access may add to: the
*Everyone can add to* row in the app's settings on the admin page (shown while shared data is on), `"append":
["queue"]` in its meta, or `append_collections` from [Claude](CONNECTOR.md). You can name up to 10 collections; a name has
at most 64 characters, uses letters, digits, `_` and `-`, and is not `data`.

- A non-admin can create a new document in such a collection. They cannot overwrite, merge into or delete one: those
  writes reject with `invalid_argument`, as for any other shared document. Admins can still change everything.
- Only the collection itself counts, not collections below a document in it. Nothing under `data/` is ever add-only.
- The hub sets `_added_by` (the e-mail in lower case) and `_added_at` (epoch seconds) when a document is created
  there. Whatever the app sends in those two fields is ignored: later writes keep the stored values, and a document
  without them (written before the collection was listed, or after *Delete my data*) stays without them. Everyone who
  can see the app can read `_added_by`, so they see who added each document. The stamp counts towards the document
  size limit. *Delete my data* keeps the documents but removes `_added_by` where it is that user's address.
- `await user.can("data.add:queue")` says whether the user may add to `queue`. It is true for admins and for apps
  without shared data.
- There is no limit per user on how many documents someone with access can add, so only list collections for apps
  shared with people you trust.

Add with `add()`, which picks a random id, so two people do not pick the same one (the second would be rejected):

```js
await db.collection("queue").add({ question: "What is new in Oslo?" });
```

If a create with a fixed id is retried, say after a dropped connection, and the retry is rejected, the first attempt
may already be saved: read the document back before telling the user it failed.

## Public sharing

Everything on the hub needs a login. Public sharing lets a user make a secret link to one app, for people who have
no account. Anyone with the link opens the app, reads what the user has made public and can leave replies of their own,
for example to claim an item on a wish list or to sign up for something. Replies can be hidden from the user, so
the app can keep a gift a surprise. Read the [security model](../README.md#security-model) first: whoever has the
link is not checked in any other way.

The settings are on the admin page, under *Public sharing* in the app's settings, in the app's `meta.json`, or from
[Claude](CONNECTOR.md#public-sharing). All of them need [shared data](#shared-data):

| Setting | |
|---|---|
| `"public": true` | Public sharing is on: users can make links to the app, and the app gets `window.claude.use("share")` and a share button in the banner. |
| `"public_read": ["products"]` | Top-level shared collections that a guest may also read, one document at a time by id (no listing, no query). Up to 10 names, the same rules as for `append`. |
| `"guests_hidden": true` | The user cannot read the replies their guests leave. Without it the user reads them, as for a sign-up list. |
| `"agent": true` | The [agent zone](#the-agent-zone) is on. |

Shared data cannot be turned off while `public`, `guests_hidden` or `agent` is on. A collection cannot be in both `append` and
`public_read`. `guests_hidden` can be turned on at any time; turning it off while there are guest replies deletes them,
see [below](#guest-replies).

### Zones

The zones are collections with fixed names directly under the user's own branch, `data/users/<e-mail>/`. They are
special only in an app that has the matching setting on; in any other app `public`, `guests` and `agent` are
ordinary collection names. The guests zone keeps its rules while `public` or `guests_hidden` is on, so turning public
sharing off does not reveal hidden replies. Everything else in the branch stays private.

| Zone | Path under the branch | The user | A guest with the user's link | An admin through Claude |
|---|---|---|---|---|
| Public | `public/<name>/...` | reads and writes | reads, for the link's `<name>` only | nothing |
| Guests | `guests/<name>/...` | see [guest replies](#guest-replies) | reads, creates, deletes their own, for the link's `<name>` only | nothing |
| Agent | `agent/...` | reads and writes | nothing | reads and writes |
| Private | anything else | reads and writes | nothing | nothing |

`<name>` is the share name, which the app chooses: for a list, say, the list's id. It has 1 to 64 characters of
letters, digits, `_` and `-` (`^[A-Za-z0-9_-]{1,64}$`). An app with only one thing to share uses `main`, the default.
The documents lie directly in the collection `public/<name>`, and collections can sit below those documents. A
document placed in `public` or `guests` without a share name is not in a zone and stays private, as does the document
`public` in the root collection.

Each share name has one link per user and app, so one user can share several lists, each with a link of its own. A guest
can only reach the share name of the link they were given, also by guessing the name of another.

### The link

The link is `https://<your domain>/p/<token>/` (folder apps also serve their other files below it). The token is 128
random bits and is kept in clear, so the user can copy the link again. The user makes, replaces and turns off links in the
share sheet, opened by the share button on the right of the banner, or under *Shared links* on the settings page.
An app cannot make links itself. Replacing a link makes the old one stop working at once. Turning one off deletes the
link and leaves the documents in the zones.

- The link works while the app has `public` on, the user can still see the app and the user is still a person on
  the hub. Otherwise, like for an unknown token, it answers 404. If public sharing is turned off, links stop working
  but are kept, and work again when it is turned on.
- Every answer carries `X-Robots-Tag: noindex, nofollow`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`,
  so the link is not indexed and does not leak to the sites a guest goes on to.
- The link goes around the user's [code lock](#code-lock): the user chose to make this part public. The share sheet says so for a locked
  app. Making, replacing or turning off a link, and clearing replies, is refused with 423 while the app is locked for the user and
  not opened on that device; reading the state of the link is not.
- A visitor who is logged in as the link's owner is sent on to the app. Anyone else, logged in or not, is a guest on
  this page.
- Visits by link are not counted. A public page does not load the service worker or pull to refresh, and has no
  back arrow, link to the front page or share button in the banner.
- The link follows the app when it is renamed. Deleting the app deletes all its links and every guest reply in it;
  the public and agent zones stay, like the rest of its data. *Delete my data* removes the user's links, their zones and the guest
  replies on their lists. Removing a person from the hub removes only their links.

### On the page

The hub adds the same `hub.js` to the public page, with no e-mail address in it. On it `window.claude.use("db")` and
`window.claude.use("user")` are `null`, so the app has to look at `share.mode` and show a guest view.

```js
const share = await window.claude.use("share");   // null in an app without public sharing
share.mode            // "owner" or "guest"
share.name            // the share name: a guest's link name; the owner's last share.scope(), else "main"
share.db              // db for the current share name, only public/... and guests/...
share.scope(name, title)  // owner: what the share button shares now; returns a db for that name
share.remove(name)    // owner: turn the link for a name off, for example when a list is deleted
share.shared          // share.shared.doc("products/k1").get(): a public_read collection, by id
```

`share.db` is the usual `db` (`doc`, `collection`, `get`, `set`, `update`, `delete`, `add`, `where`, `orderBy`, `limit`,
`onSnapshot`), rooted in the user's branch and one share name, and it reaches only `public/...` and `guests/...`; any
other path rejects with `invalid_argument`. The owner's `share.db.doc("public/abc")` is stored as
`data/users/<e-mail>/public/<name>/abc`, and the guest reads the same path `public/abc`, so neither needs the
e-mail or the share name. A guest creates with `set` or `add` and deletes with `delete`; `update` rejects with
`invalid_argument` on a public page, without a request. `scope(name, title)` throws at once for a name that does not fit the rule above, and `remove(name)` returns a rejected promise; `title` is
only shown in the share sheet and on the settings page. A guest cannot call `scope` or `remove`.

The share sheet follows the device's light or dark setting. It shows the link, how many replies there are (never what they say),
and for the user:
*Copy*, *New link*, *Turn off* and *Clear guests' replies*, the last three after a confirmation. Clearing deletes the
user's guest zone for that share name and is the way out if someone with the link has taken everything or filled the
quota; it never touches `public/`.

### Guest replies

A guest can create a document in `guests/...` and delete one they created, nothing else: never overwrite, merge into
or delete another's. The first time, `hub.js` makes a random secret in the guest's `localStorage` and sends it with each
request. The hub stores only its hash in the field `_guest`, and deleting needs the same secret. A guest on another device or in
another browser is another guest.

- A create with a fixed id is allowed, and the second guest to use the same id is refused. That is how an app makes
  "only one person can take this".
- `_guest` is never returned to anyone. A guest reads `_mine: true` or `false` on each document in the zone instead.
  The hub also sets `_added_at`. What a guest sends in `_guest`, `_mine`, `_added_by` and `_added_at` is dropped.
- A guest reads every document in `guests/...` of their link, other guests' too. Do not ask guests for anything that
  other guests may not see.
- The user never creates or changes documents in their own guests zone: the write rejects with `invalid_argument`. They may
  delete one by its path, and that answers the same whether or not the document existed, so it also works when the
  zone is hidden.
- With `guests_hidden` the user reads nothing in their guests zone: not in the app, in `GET /api/store/<slug>`, in Claude
  or in a card recipe. This stops accidents, such as Claude reading out a surprise; it does not stop a user who
  wants to see. The share sheet still counts the replies.
- `guests_hidden` cannot be turned off through Claude while there are replies. On the admin page, turning it off deletes every guest
  reply in the app after a confirmation. So no single click or message to Claude reveals what was hidden. Turning it on is always allowed.
- `public_read` collections are read with `share.shared.doc("<collection>/<id>").get()`, by owner and guest alike. Any
  other path, a collection below such a document included, rejects with `invalid_argument` before any request, for the
  owner too, so a page tried out as the owner behaves the same for a guest. The
  guest gets the document without the hub's fields (`_added_by`, `_added_at`). The app puts the ids in the user's public
  zone, so a guest only finds what the user points at. In any zone a guest reads documents without `_added_by`.

Limits:

| | |
|---|---|
| A guest document | 4096 bytes as sent (`413` above that). JSON that is not an object, with `NaN` or `Infinity`, nested deeper than 32 levels, or with a lone surrogate in a string is refused with `400`. |
| Guest documents per link | 500, collections below them included (`429`). |
| Writes per hour | 30 per IP address and 200 per link (`429`). A create or delete counts once its path and guest secret have been checked: a malformed path, a path outside the two zones, a write to `public/...` or a missing secret does not count. After that it counts even if it is refused: a body too large or not valid, a link that is full or a taken id, and deleting a reply that is missing or someone else's. A write refused by the limit itself does not count. Counted in memory, so a restart resets them. |

The per-address limit counts the client address as the reverse proxy reports it in `X-Forwarded-For`: the image runs
`uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*`, as the login limit relies on too. A proxy
that does not set the header makes all guests share one allowance of 30 writes an hour. A hub reachable without its
proxy lets a guest set the header and dodge the per-address limit. The per-link limit and the 500-document cap hold either way.

The guest API is `/api/public/<token>/...`, used by `hub.js`, and it answers `404` for a missing or dead link on every route. A write
to `public/...` gives `403`, a path outside the two zones `404`, a second creator of the same id `403`, deleting someone
else's reply `403`, and a malformed path or a missing guest secret `400`. In `hub.js` a `429` rejects with the code
`resource_exhausted` on a public page; other refusals (`400`, `403`, `404`, `413`) reject with `invalid_argument`.

### The agent zone

With `"agent": true`, an admin reads and writes `data/users/<anyone's e-mail>/agent/...` through Claude and
`GET`/`PUT /api/store/<slug>/d` and `/c`, in addition to the user's own access. It lets a scheduled agent, which always
runs as an admin, do a job for every user of the app. `list_app_data` without a collection then also lists other users'
agent zones, so the agent finds every user who put something there. The rest of someone's branch stays invisible, to admins too.

The app has to tell the user what ends up in the agent zone: an admin reads all of it.

### Example: a shared list

One page for the owner and for guests. The owner adds items to `public/<id>`. A guest sees the items, takes one by
creating `guests/<id>` with the item's id, and can undo it. With *Hide guests' replies* on, the owner does not
see who took what.

```html
<h1>Cabin trip</h1>
<ul id="list"></ul>
<form id="add" hidden><input id="text" required> <button>Add</button></form>
<p id="note"></p>
<script>
(async () => {
  const share = await window.claude.use("share");
  if (!share) return;                         // an app without public sharing
  const owner = share.mode === "owner";
  if (owner) share.scope("cabin", "Cabin trip");   // what the Share button in the banner shares
  const db = share.db;                        // the same paths for the owner and for a guest
  const note = (text) => { document.getElementById("note").textContent = text; };
  let items = [], claims = new Map();

  function draw() {
    const list = document.getElementById("list");
    list.replaceChildren(...items.map((item) => {
      const li = document.createElement("li");
      const claim = claims.get(item.id);
      li.append(item.data().text + (claim ? " (taken)" : " "));
      if (!owner && !claim) {
        const take = document.createElement("button");
        take.textContent = "I'll take this";
        take.addEventListener("click", () => takeItem(item.id));
        li.append(take);
      }
      if (!owner && claim && claim.data()._mine) {   // a guest sees _mine on their own documents
        const undo = document.createElement("button");
        undo.textContent = "Undo";
        undo.addEventListener("click", () => db.doc("guests/" + item.id).delete().catch((e) => note(e.message)));
        li.append(undo);
      }
      return li;
    }));
  }

  async function takeItem(id) {
    try {
      await db.doc("guests/" + id).set({ at: Date.now() });   // the id is the item's: only one guest gets it
    } catch (e) {
      note(e.code === "resource_exhausted" ? "Too many tries, wait a while." : "Someone else just took it.");
    }
  }

  db.collection("public").onSnapshot((snap) => { items = snap.docs; draw(); });
  db.collection("guests").onSnapshot((snap) => { claims = new Map(snap.docs.map((d) => [d.id, d])); draw(); });

  if (owner) {
    const form = document.getElementById("add");
    form.hidden = false;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("text");
      await db.collection("public").add({ text: input.value });
      input.value = "";
    });
  }
})();
</script>
```

The calls it makes, for the owner then for a guest on `/p/<token>/` (the example was run against `hub.js` in a
test harness that records them):

| | Owner | Guest |
|---|---|---|
| Items | `GET /api/store/<slug>/c?path=data/users/<e-mail>/public/cabin` | `GET /api/public/<token>/c?path=public` |
| Replies | `GET /api/store/<slug>/c?path=data/users/<e-mail>/guests/cabin` | `GET /api/public/<token>/c?path=guests` |
| Add an item | `PUT /api/store/<slug>/d?path=data/users/<e-mail>/public/cabin/<id>` | refused, so the form is not shown |
| Take an item | | `PUT /api/public/<token>/d?path=guests/<id>` with `X-Hub-Guest` |
| Undo | | `DELETE /api/public/<token>/d?path=guests/<id>` |

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

## Code lock

Everyone can lock apps behind a four-digit code on the settings page. An app has to do nothing for this: the hub
shows the code screen before the app loads, keeps the app's pages, files and storage APIs shut until the code is
entered, and reloads the page when the lock closes. Link cards cannot be locked.

- **Keep sensitive data on the server.** The lock covers `window.claude.use("db")` and the key/value API. It does not
  cover what an app puts in `localStorage`, IndexedDB or a service worker cache.
- **Use the app's address as its name** in the key/value API (`/api/data/<app>`). The lock goes by that name, so data
  under another name is not covered. After the app is renamed, its data stays under the old name.
- **Save text as it is typed.** A locked app opens for 10 minutes after the last time it was on screen, then reloads
  to the code screen. Anything not saved by then is lost.

## Offline

The *Works offline* switch in an app's settings on the admin page (or `offline: true` through the connector) makes the
hub keep the app on the phone. The hub's service worker stores the app's page and the files it loads from its own
folder, and opens them if the server does not answer within 3 seconds. The front page is kept too, so the app can be
found without a connection. The switch is for single-file and folder apps; link cards cannot have it.

Only the page and its files are stored, never data. The hub's storage APIs need the server, so an app marked for
offline use has to do its own bookkeeping:

- **Keep the data on the device** (`localStorage` or IndexedDB) and send it to the server later, when there is a
  connection again.
- **Save text as it is typed.** An iPhone can drop a home-screen app from memory at any time.
- **Do not register a service worker of your own.** The hub's worker already covers the app, and a narrower one in the
  app's folder would take over and hide the hub's copy.

The hub stores a copy by fetching the app's page with an `X-Hub-Precache: 1` header. That is not counted as a visit in
the statistics. The server is asked first, so a connection gives the current app when the server answers within about
3 seconds. Once it has not, the files the app loads come from their copies for the next 30 seconds, or until the
server answers in time again, so a weak connection does not add a wait for each file.

The page's copy is refreshed whenever the front page or the app is opened online. The files from the app's folder are
stored when the app itself is opened online: a refresh from the front page fetches only the page. The copies are
dropped when the switch is turned off. An app behind a [code lock](#code-lock) is never stored, and turning the lock
on for an app deletes the copy on that device.

### Back to the front page

When the hub is installed as a home-screen app and the session started at the front page, coming back to an app after
two minutes away shows the front page again instead of the app left behind. The page stays put when:

- it has called `window.hubStay(true)`. Call `window.hubStay(false)` to let it go back again. The app may also run
  outside the hub, so write `window.hubStay?.(true)`;
- a visible field the user has typed into holds text that is not empty and differs from what the page put there.
  Values set by a script do not count. Text the app has already autosaved still keeps the page while it shows, so
  still save input as it is typed.

## A line on the front-page card

In a list (an open section), an app can show one line of text under its name, such as a count or today's total. The best way
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

`hubCard` gets `{ db, today, now, timeZone, user }` and returns a string, or `null` for no line (it may be `async`).

- `db` is read-only: `db.doc(path).get()`, `db.collection(path).get()`, and `.where(field, op, value)`,
  `.orderBy(field, dir)` and `.limit(n)` on a collection (a collection read sees at most the 500 documents with the
  highest ids). It reads what the viewer sees in the app: personal data, or in an app with shared data the shared
  documents and the viewer's own branch.
- `user` is the viewer's e-mail address in lower case, so a recipe in an app with shared data can find the viewer's own
  branch, `data/users/<e-mail>/`. A guests zone that is hidden from its owner reads as empty here too.
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
