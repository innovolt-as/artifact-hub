# The Claude connector

The hub is a remote MCP server with OAuth at `https://<your domain>/mcp`. Added as a custom connector in claude.ai,
it lets Claude list, publish and edit apps, and read and write their data, from any conversation. It has only been
tested with claude.ai.

## Adding it

Once, in claude.ai in a browser: *Settings → Connectors → Add custom connector*, and paste the URL. After that the
connector is available in every conversation, including the iOS and Android apps.

claude.ai then sends you to the hub to log in. With magic links, the link opens in a new tab; carry on there. Then
press *Give access* on the consent page. Only addresses in `ADMIN_EMAILS` can connect; anyone else is turned away.

Ask things like "put this in the hub", "update the timesheet in the hub" or "make the timesheet visible to
everyone".

## Tools

| Tool | |
|---|---|
| `list_apps` | All apps and link cards: slug, title, who has access, whether the data is personal or shared, the [public sharing](#public-sharing) settings (`public`, `public_read`, `guests_hidden`, `agent`), whether it can be edited. |
| `get_app` | The HTML of an app, its settings as `list_apps` shows them, and in `card` the line its [card recipe](APPS.md#a-line-on-the-front-page-card) gives right now, or the recipe's error, so Claude can check a recipe right after writing it. |
| `create_app` | Publishes a new single-file app (`slug`, `html`, `title`, optional `description`, `emoji`, `private`, `shared_data`, `offline`, and the public sharing settings `public_sharing`, `public_read`, `guests_hidden`, `agent_zone`). |
| `update_app` | Replaces the whole HTML of an app. |
| `edit_app` | Small changes: a list of `{old, new}` replacements, applied all or nothing. |
| `update_app_info` | Changes title, description, emoji, `private`, `shared_data`, `offline` (the [*Works offline* switch](APPS.md#offline)), `append_collections` or the [public sharing](#public-sharing) settings without touching the HTML. |
| `list_app_data`, `get_app_data`, `set_app_data`, `delete_app_data` | Read and write the documents an app keeps with `window.claude.use("db")`: the data of the user behind the connection, or in an app with shared data the shared documents and that user's own `data/users/<e-mail>/` branch., and, where the app has the agent zone on, every user's `data/users/<e-mail>/agent/` too. |

The data tools let you, say, tell Claude what you had for lunch and have it log that in your food diary app.

`update_app` and `edit_app` work on single-file apps and on the `index.html` of folder apps; the other files in a
folder (images, a service worker) stay as they are. Link cards can only be changed with `update_app_info`. The
connector cannot delete apps.

New apps from Claude are only visible to admins until you share them, either under *Access* in the app's settings on
the admin page or by asking Claude to set `private: false` (everyone who can log in). Sharing with specific people is done on
the admin page. `private` leaves an existing list of people alone; it comes back if *Specific people* is chosen
again.

Every replacement keeps the old version, as described in [APPS.md](APPS.md#versions).

## Shared data

An app that Claude or a scheduled agent fills with the same content for everyone needs
[shared data](APPS.md#shared-data); otherwise the content lands in the data of whoever runs the agent, and nobody
else sees it. Before Claude creates an app whose content it will write, it asks whether that content is the same
for everyone or personal, and sets `shared_data` to match. `update_app_info` with `shared_data` switches an
existing app; `copy_my_data=true` also copies your current documents into the shared data.

`append_collections` takes a list of names, for example `["queue"]`, and lets everyone who can see a shared-data app
add new documents to those [collections](APPS.md#collections-everyone-can-add-to) but not change or delete them; an
empty list turns it off. `list_apps` and `get_app` show the names as `"append"`. Only list collections for apps shared with people
you trust: there is no limit per user on how many documents they can add.

The admin page warns about an app that is shared with others but has personal data that Claude has written in the
last 30 days: in practice it only works for you. Claude passes on the same warning when it shares such an app.

## Public sharing

[Public sharing](APPS.md#public-sharing) lets users make secret links to an app, for people without an account. Claude
changes four settings with `update_app_info`, or `create_app` for a new app. All need shared data to be on first.

| Parameter | |
|---|---|
| `public_sharing` | `true` lets users make links. `false` stops the links working; they are kept and work again when it is turned on. |
| `public_read` | A list of top-level shared collections, up to 10, that guests may read one document at a time by id. A collection cannot also be in `append_collections`. `[]` turns it off. |
| `guests_hidden` | `true` hides the guests' replies from their owner, and from Claude. `false` is refused while there are replies; do it on the admin page, which deletes them after a confirmation. |
| `agent_zone` | `true` lets an admin read and write `data/users/<any e-mail>/agent/...`. |

Shared data cannot be turned off while `public_sharing` or `agent_zone` is on. If one of these is refused when an app
is created, the app is still created; if it is refused after other changes in `update_app_info`, Claude says what went
through before the refusal. Claude only changes the settings when asked.

Claude does not make or turn off links: the user does that in the share sheet (the button in the banner) or under *Shared
links* on the settings page. The data tools follow the zones. Claude never reads a guests zone that is hidden, and with the
agent zone on, an admin reads and writes other users' `agent/` paths, and `list_app_data` without a collection lists
them. Nothing else in another user's branch is visible. Claude should never put anything sensitive in `public/`, since
anyone with the link reads it. The connector's instructions tell Claude all of this, and how an app reaches the zones
through `window.claude.use("share")`.

## Code lock

If you have set a [code](APPS.md#code-lock), the page where you approve a new connection asks for it, so someone
holding your logged-in phone cannot connect their own Claude. *Cancel* needs no code, and existing connections are not
affected.

The connector reaches locked apps without a code. Reading, writing and updating work as for any other app, and
anyone who can ask the Claude app on your phone can have it read them out.

## Revoking access

Remove the address from `ADMIN_EMAILS` and run `docker compose up -d`. Every call checks the address against the
current settings, so this takes effect as soon as the hub has restarted.

To cut all connections at once, delete the rows in the `oauth_tokens` table in `data/hub.db` (and, if you like,
`oauth_codes`, `oauth_requests` and `oauth_clients`). That works immediately.

This only concerns the connector. To stop someone logging in to the hub itself, use *Remove* under *People* on the
admin page.
