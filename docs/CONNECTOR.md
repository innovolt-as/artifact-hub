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
| `list_apps` | All apps and link cards: slug, title, who has access, whether it can be edited. |
| `get_app` | The HTML of an app. |
| `create_app` | Publishes a new single-file app (`slug`, `html`, `title`, optional `description`, `emoji`, `private`). |
| `update_app` | Replaces the whole HTML of an app. |
| `edit_app` | Small changes: a list of `{old, new}` replacements, applied all or nothing. |
| `update_app_info` | Changes title, description, emoji or `private` without touching the HTML. |
| `list_app_data`, `get_app_data`, `set_app_data`, `delete_app_data` | Read and write the documents an app keeps with `window.claude.use("db")`, for the user behind the connection only. |

The data tools let you, say, tell Claude what you had for lunch and have it log that in your food diary app.

`update_app` and `edit_app` work on single-file apps and on the `index.html` of folder apps; the other files in a
folder (images, a service worker) stay as they are. Link cards can only be changed with `update_app_info`. The
connector cannot delete apps.

New apps from Claude are only visible to admins until you share them, either with the access button on the admin
page or by asking Claude to set `private: false` (everyone who can log in). Sharing with specific people is done on
the admin page. `private` leaves an existing list of people alone; it comes back if *Specific people* is chosen
again.

Every replacement keeps the old version, as described in [APPS.md](APPS.md#versions).

## Revoking access

Remove the address from `ADMIN_EMAILS` and run `docker compose up -d`. Every call checks the address against the
current settings, so this takes effect as soon as the hub has restarted.

To cut all connections at once, delete the rows in the `oauth_tokens` table in `data/hub.db` (and, if you like,
`oauth_codes`, `oauth_requests` and `oauth_clients`). That works immediately.

This only concerns the connector. To stop someone logging in to the hub itself, use *Remove* under *People* on the
admin page.
