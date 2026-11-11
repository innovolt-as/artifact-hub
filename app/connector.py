"""The Claude connector: a remote MCP server at /mcp with tools to list, read, create and change apps.

Mounted on "/" at the bottom of app.main, after every FastAPI route, so it only sees /mcp and the
OAuth endpoints the SDK adds (/authorize, /token, /register, /revoke, /.well-known/...).
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import AnyHttpUrl, BaseModel, Field

from app import i18n
from app import main as hub
from app import public
from app.oauth import HubOAuthProvider

INSTRUCTIONS = f"""\
Publish and maintain HTML apps on {hub.SITE_NAME} ({hub.BASE_URL}): single pages, and the index.html of folder apps.
Use list_apps to find an app's slug. Use create_app only for a brand-new app; new apps are private
(only admins see them) until the user asks to share them. Before update_app or edit_app, call get_app
unless the app's current source is already in the conversation. Prefer edit_app for small changes.
Only publish or change apps when the user explicitly asks you to.

The hub puts a fixed banner at the top of every app page. Give a sticky or fixed top bar
top: var(--hub-banner-h, 0px) (or var(--hub-banner-h, <its current top>)) so it sits right under the banner.

Apps also keep data (what they read and write through window.claude.use("db")). By default an app's data is
personal: list_app_data, get_app_data, set_app_data and delete_app_data reach the data of the user behind this
connection only. An app can have shared data instead (list_apps shows "data": "shared"): then every document is
shared by everyone who can see the app and only admins change it, except each user's own branch
data/users/<their e-mail>/..., which stays private to that user. The data tools pick shared or private from the
path. Before writing, read the app's source (get_app) and existing documents so the format matches what the app
expects. Write data when the user asks you to log, add or change something in an app.

When you build an app whose content Claude or a scheduled agent will write, ask the user before create_app
whether that content is the same for everyone who can open the app (shared_data=true) or personal to each user,
and pass shared_data accordingly. In a shared app, put anything personal under data/users/<the user's e-mail>/,
and say in the app's guide (meta/guide) what is shared and what is personal. update_app_info(shared_data=...)
switches an existing app; copy_my_data=true also copies the user's current documents into the shared data, where
everyone with access sees them, so check them for personal content first.
In a shared app, update_app_info(append_collections=[...]) names collections everyone with access may add new
documents to (not change or delete); the hub stamps each with _added_by and _added_at. list_apps and get_app show them as "append".
An app can be marked to work offline (update_app_info offline=true); only do that for apps that keep their own data on the device and send it later.
Public sharing (update_app_info public_sharing=true, needs shared data) lets a user hand out a link that works without
logging in: a visitor reads data/users/<e-mail>/public/<name>/... and reads, adds and deletes their own documents in
data/users/<e-mail>/guests/<name>/..., and an app asks for a link with window.claude.use("share") and scope(name, title).
Never put anything sensitive under public/, since anyone with the link reads it. public_read=[collections] also opens
whole shared collections to guests, guests_hidden=true hides the guests' replies from their owner (so they cannot be read
here, and guests_hidden cannot be turned off here once replies exist), and agent_zone=true lets a scheduled agent serve
every user through data/users/<e-mail>/agent/... (an admin reads and writes those paths, and list_app_data shows them).
list_apps and get_app show these settings as public, public_read, guests_hidden and agent.
A user can lock an app behind a code on the hub; the lock covers the hub's own storage, not the browser's, so keep
anything sensitive in window.claude.use("db"), never in localStorage.

The hub's front page can show one line from each app on its card. Give the app a card recipe: a
<script data-hub-card> block with a function hubCard({{ db, today, now, timeZone, user }}) that returns the line as a
string (or null for none), e.g.
<script data-hub-card>async function hubCard({{ db, today }}) {{ const d = await db.doc(`days/${{today}}`).get(); return d.exists ? d.data().kcal + " kcal" : null; }}</script>
The recipe is read-only (db.doc(path).get(), and db.collection(path).get() with .where(...), .orderBy(...) and
.limit(...); a collection read sees at most the 500 documents with the highest ids), has no network and no DOM, gets
only plain functions, and has 0.25 s. today is the viewer's date as YYYY-MM-DD, now is milliseconds and timeZone the
viewer's zone, and user the viewer's e-mail in lower case (to read the viewer's own branch,
data/users/<user>/..., in a shared-data app). Every read of a path the hub has not handed the recipe yet ends a round: the hub reads what that round
asked for and runs the recipe again. There are at most {hub.cards.MAX_ROUNDS} rounds and {hub.cards.MAX_READS} paths
per round, so read in parallel (Promise.all) or read a whole collection with where/orderBy/limit, not one document at
a time in a loop with await (such a loop over seven days fails with too_many_reads). The server runs the recipe
every time the front page is shown, so the line is always current. get_app shows what it gives in the card field:
{{"text": <the line, or null>}}, or {{"error": <code>}} with the code timeout (over 0.25 s, reads included), memory
(over 32 MB), no_function (no hubCard), not_text (returned something other than a string or null), too_many_reads
(more rounds or paths than above), bad_path (asked for a path the hub cannot read) or failed: <message> (a syntax
error or a throw). Add a recipe when the app has a natural headline number. Only a line that cannot be computed
from the stored data is written by the app itself as the document hub/summary =
{{"text": "<one short line, e.g. 93 hits ▼1>"}} (db.doc("hub/summary").set(...)); that is the fallback when there is
no recipe or it fails."""


class Edit(BaseModel):
    old: str = Field(description="Exact text in the current page; must occur exactly once.")
    new: str = Field(description="Replacement text.")


def _error(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


def _user() -> str:
    """The admin behind this call. The token check already does this; checked again to be safe."""
    token = get_access_token()
    email = token.subject if token else None
    if not hub.is_admin(email):
        raise hub.HubError(i18n.t("mcp.admin_only"))
    return email


def _state(on: bool) -> str:
    return i18n.t("mcp.state_on" if on else "mcp.state_off")


def _set_public(slug: str, public_sharing: bool | None, public_read: list[str] | None,
                guests_hidden: bool | None, agent_zone: bool | None) -> dict | None:
    """Apply the public sharing settings that were given; None when none were. Shared data must already be on."""
    if public_sharing is None and public_read is None and guests_hidden is None and agent_zone is None:
        return None
    return hub.set_public(slug, public=public_sharing, public_read=public_read, guests_hidden=guests_hidden,
                          agent=agent_zone, via_connector=True)


def _url(slug: str) -> str:
    return f"{hub.BASE_URL}/a/{slug}/"


def build_mcp() -> MCPServer:
    mcp = MCPServer(
        name=hub.SITE_NAME,
        instructions=INSTRUCTIONS,
        auth_server_provider=HubOAuthProvider(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(hub.BASE_URL),
            resource_server_url=AnyHttpUrl(f"{hub.BASE_URL}/mcp"),
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
            validate_token_resource=False,
        ),
    )

    @mcp.tool(
        name="list_apps",
        title="List apps",
        description="List every app and link card on the hub, with slug, title, description, URL, who has access "
        "(a short label in the hub's language: everyone who can log in, only admins, or specific people chosen on "
        "the admin page), whether its data is personal or shared, and whether it is editable (pages and folder apps are; "
        "link cards are not). Use this to find the slug of an "
        "existing app before get_app, update_app, edit_app or update_app_info.",
        annotations=ToolAnnotations(readOnlyHint=True),
        structured_output=False,
    )
    def list_apps() -> str:
        try:
            user = _user()
        except hub.HubError as e:
            return _error(str(e))
        apps = [
            {
                "slug": a["slug"],
                "title": a["title"],
                "description": a["description"],
                "emoji": a["emoji"],
                "kind": a["kind"],
                "url": a["url"] if a["kind"] == "link" else _url(a["slug"]),
                "access": a["access_text"],
                "data": a["data"],
                "append": a["append"],
                "public": a["public"],
                "public_read": a["public_read"],
                "guests_hidden": a["guests_hidden"],
                "agent": a["agent"],
                "editable": a["kind"] in ("page", "app"),
                "updated": datetime.fromtimestamp(a["updated"], timezone.utc).isoformat(timespec="seconds"),
            }
            for a in hub.list_artifacts(user)
        ]
        return json.dumps(apps, ensure_ascii=False, indent=1)

    @mcp.tool(
        name="get_app",
        title="Get app source",
        description="Return the current HTML source of an app (for a folder app: its index.html), with its title, description, emoji and kind, "
        "and \"card\": the line its card recipe gives on the front page right now ({\"text\": <the line, or null for "
        "none>}, {\"error\": <code>}, or null without a recipe). "
        "Call this before update_app or edit_app "
        "unless the app's current source is already in the conversation. Use list_apps to find the slug.",
        annotations=ToolAnnotations(readOnlyHint=True),
        structured_output=False,
    )
    def get_app(slug: str) -> str:
        try:
            user = _user()
            html = hub.page_source(slug)
            info = next((a for a in hub.list_artifacts(user) if a["slug"] == slug), {})
            with hub.db() as con:
                tz = hub.home.get_prefs(con, user)["tz"]
            result = hub.card_result(user, slug, tz)
        except hub.HubError as e:
            return _error(str(e))
        # the line exactly as the front page shows it (blank is null), or the recipe's error
        card = (None if result is None else {"error": result.error} if result.error
                else {"text": hub.home.card_line(result.text)})
        return json.dumps({"slug": slug, "title": info.get("title", ""), "description": info.get("description", ""),
                           "emoji": info.get("emoji", ""), "kind": info.get("kind", ""),
                           "data": info.get("data", "personal"), "append": info.get("append", []),
                           "public": info.get("public", False), "public_read": info.get("public_read", []),
                           "guests_hidden": info.get("guests_hidden", False), "agent": info.get("agent", False),
                           "html": html, "card": card},
                          ensure_ascii=False)

    @mcp.tool(
        name="create_app",
        title="Create app",
        description="Publish a NEW single-file HTML app (a complete HTML document, max 1 MB) at /a/<slug>/. "
        "Only for apps that do not exist yet; it fails if the slug is taken (use list_apps to check, and "
        "update_app or edit_app to change an existing app). New apps are private (only admins see them) "
        "unless private=false (everyone who can log in); leave them private until the user explicitly asks to share them. "
        "Sharing with specific people is done on the hub's admin page. "
        "Only call this when the user explicitly asks to publish. "
        "If Claude or a scheduled agent will write the app's content, first ask the user whether it is the same for "
        "everyone who can open the app (shared_data=true) or personal to each user (the default). "
        "offline=true marks an app that keeps its own data on the device, so the hub stores its page on the phone. "
        "public_sharing, public_read, guests_hidden and agent_zone set the public sharing settings and need "
        "shared_data=true (see update_app_info). "
        "slug: lowercase letters, digits, '.', '-', '_'. emoji: one emoji used as the gallery icon.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
        structured_output=False,
    )
    def create_app(slug: str, html: str, title: str, description: str | None = None, emoji: str | None = None,
                   private: bool = True, shared_data: bool | None = None, offline: bool = False,
                   public_sharing: bool | None = None, public_read: list[str] | None = None,
                   guests_hidden: bool | None = None, agent_zone: bool | None = None) -> str:
        try:
            _user()
            hub.save_page(slug, html, create=True, title=title, description=description, emoji=emoji,
                          private=private)
            if shared_data:
                hub.set_data_mode(slug, True)
            if offline:
                hub.set_offline(slug, True)
            _set_public(slug, public_sharing, public_read, guests_hidden, agent_zone)
        except hub.HubError as e:
            return _error(str(e))
        return i18n.t("mcp.created_private" if private else "mcp.created", url=_url(slug))

    @mcp.tool(
        name="update_app",
        title="Replace app",
        description="Replace the whole HTML of an EXISTING app (max 1 MB); the previous version is kept. For a folder "
        "app this replaces its index.html and leaves its other files (scripts, images, service worker) as they are. "
        "Fails if the slug does not exist or is a link card. Use list_apps to "
        "find the slug and call get_app first unless the current source is already in the conversation. "
        "For small changes prefer edit_app. Fields left out (title, description, emoji, private) stay as "
        "they are; private=true means only admins, private=false everyone who can log in. "
        "Only call this when the user explicitly asks to publish the change.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
        structured_output=False,
    )
    def update_app(slug: str, html: str, title: str | None = None, description: str | None = None,
                   emoji: str | None = None, private: bool | None = None) -> str:
        try:
            _user()
            hub.save_page(slug, html, create=False, title=title, description=description, emoji=emoji,
                          private=private)
        except hub.HubError as e:
            return _error(str(e))
        return i18n.t("mcp.updated", url=_url(slug))

    @mcp.tool(
        name="edit_app",
        title="Edit app",
        description="Make small changes to an EXISTING app by replacing exact snippets of its HTML (for a folder app: its index.html). "
        "Each 'old' must match the current source exactly once; either all edits apply or none do. "
        "Prefer this over update_app for small changes. Call get_app first unless the current source is "
        "already in the conversation; use list_apps to find the slug. Does not work on link cards. "
        "Only call this when the user explicitly asks to publish the change.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
        structured_output=False,
    )
    def edit_app(slug: str, edits: list[Edit]) -> str:
        try:
            _user()
            if not edits:
                raise hub.HubError(i18n.t("mcp.no_edits"))
            hub.edit_page(slug, [(e.old, e.new) for e in edits])
        except hub.HubError as e:
            return _error(str(e))
        return i18n.tn("mcp.edited", len(edits), url=_url(slug))

    @mcp.tool(
        name="update_app_info",
        title="Change app info",
        description="Change the gallery info of an existing app or link card without touching its HTML: title, "
        "description, emoji, or private. Fields left out stay as they are; an empty string removes the field. "
        "private=true makes it visible to admins only; private=false shares the app with everyone who can log in: "
        "only do that when the user explicitly asks. Sharing with specific people is done on the hub's admin page "
        "(a list of people is kept when private changes). "
        "shared_data=true gives the app shared data (everyone who can see it reads it, only admins change it, and "
        "data/users/<e-mail>/ stays private to each user); false makes it personal again. Nothing is deleted either "
        "way. copy_my_data=true also copies the user's documents into the shared data when it has none yet: check "
        "them for personal content first. "
        "offline=true marks an app that keeps its own data on the device, so the hub stores its page on the phone; "
        "false takes the mark off. "
        "append_collections=[names] lets everyone who can see a shared-data app add new documents to those top-level "
        "collections, but not change or delete them (the hub stamps _added_by and _added_at); [] turns it off. "
        "public_sharing=true lets users make links that work without logging in (needs shared data; guests read "
        "data/users/<e-mail>/public/<name>/ and write only their own documents in data/users/<e-mail>/guests/<name>/); "
        "public_read=[names] also opens those shared collections to guests (a collection cannot be in both "
        "public_read and append_collections); guests_hidden=true hides the guests' replies from their owner, and "
        "false is refused here while replies exist; agent_zone=true lets an admin and a scheduled agent read and "
        "write data/users/<any e-mail>/agent/. Only change these when the user asks. "
        "Use list_apps to find the slug.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
        structured_output=False,
    )
    def update_app_info(slug: str, title: str | None = None, description: str | None = None,
                        emoji: str | None = None, private: bool | None = None, shared_data: bool | None = None,
                        copy_my_data: bool = False, offline: bool | None = None,
                        append_collections: list[str] | None = None, public_sharing: bool | None = None,
                        public_read: list[str] | None = None, guests_hidden: bool | None = None,
                        agent_zone: bool | None = None) -> str:
        try:
            user = _user()
            hub.set_info(slug, title=title, description=description, emoji=emoji, private=private)
            said = [i18n.t("mcp.info_updated", slug=slug)]
            if shared_data is not None:
                existed = shared_data and copy_my_data and hub.share_preview(slug, user)["shared_exists"]
                copied = hub.set_data_mode(slug, shared_data, copy_from=user if copy_my_data else None)
                if existed:  # nothing is copied over shared data the app already has
                    said.append(i18n.t("mcp.data_shared_exists"))
                else:
                    said.append(i18n.tn("mcp.data_shared", copied) if shared_data else i18n.t("mcp.data_personal"))
            if offline is not None:
                hub.set_offline(slug, offline)
                said.append(i18n.t("mcp.offline_on" if offline else "mcp.offline_off", slug=slug))
            if append_collections is not None:
                names = hub.set_append(slug, append_collections)
                said.append(i18n.t("mcp.append_set", names=", ".join(names)) if names else i18n.t("mcp.append_off"))
                info = next((a for a in hub.list_artifacts(user) if a["slug"] == slug), {})
                if names and info.get("data") != "shared":
                    said.append(i18n.t("mcp.append_needs_shared"))
            settings = _set_public(slug, public_sharing, public_read, guests_hidden, agent_zone)
            if settings:
                said.append(i18n.t("mcp.public_set", public=_state(settings["public"]),
                                   read=", ".join(settings["public_read"]) or "-",
                                   hidden=_state(settings["guests_hidden"]), agent=_state(settings["agent"])))
            if private is False and slug in hub.claude_warned(hub.list_artifacts(user)):
                said.append(i18n.t("mcp.claude_warning"))
        except hub.HubError as e:
            return _error(str(e))
        return " ".join(said)

    @mcp.tool(
        name="list_app_data",
        title="List app data",
        description="Show what the user has stored in an app (the documents the app reads and writes through "
        "window.claude.use('db')); in an app with shared data, the shared documents and the user's own "
        "data/users/<e-mail>/ branch. Without collection: an overview {collection: [document ids]}. With a collection "
        "path (odd number of segments, e.g. 'days'): {document id: data} for that collection (at most 500).",
        annotations=ToolAnnotations(readOnlyHint=True),
        structured_output=False,
    )
    def list_app_data(slug: str, collection: str | None = None) -> str:
        try:
            user = _user()
            out = hub.doc_list(slug, user, collection) if collection else hub.doc_overview(slug, user)
        except hub.HubError as e:
            return _error(str(e))
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool(
        name="get_app_data",
        title="Read app data",
        description="Read one document from the user's data in an app. path has an even number of segments, "
        "e.g. 'days/2026-10-22' or 'settings/main'. Returns {\"path\", \"exists\", \"data\"}.",
        annotations=ToolAnnotations(readOnlyHint=True),
        structured_output=False,
    )
    def get_app_data(slug: str, path: str) -> str:
        try:
            data = hub.doc_get(slug, _user(), path)
        except hub.HubError as e:
            return _error(str(e))
        return json.dumps({"path": path, "exists": data is not None, "data": data}, ensure_ascii=False)

    @mcp.tool(
        name="set_app_data",
        title="Write app data",
        description="Write one document in the user's data for an app; the app sees it the next time it loads or "
        "polls. path has an even number of segments, e.g. 'days/2026-10-22'. data is a JSON object. "
        "merge=false replaces the document; merge=true deep-merges objects into an existing one (lists are "
        "replaced, so to add to a list: get_app_data, append, and write the whole list). Match the format the app "
        "uses: read its source with get_app and existing documents first. In an app with shared data, paths under "
        "data/users/<the user's e-mail>/ are the user's private data and every other path is shared. "
        "Only write when the user asks.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
        structured_output=False,
    )
    def set_app_data(slug: str, path: str, data: dict, merge: bool = False) -> str:
        try:
            stored = hub.doc_set(slug, _user(), path, data, merge=merge)
        except hub.HubError as e:
            return _error(str(e))
        return json.dumps({"ok": True, "path": path, "data": stored}, ensure_ascii=False)

    @mcp.tool(
        name="delete_app_data",
        title="Delete app data",
        description="Delete one document from the user's data in an app (path like 'days/2026-10-22'). "
        "In the user's own guests/ zone the reply says only that the request was handled, never whether a "
        "document existed. "
        "Only when the user explicitly asks to delete it.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
        structured_output=False,
    )
    def delete_app_data(slug: str, path: str) -> str:
        try:
            gone = hub.doc_delete(slug, _user(), path)
        except hub.HubError as e:
            return _error(str(e))
        zone = public.zone_of(path)
        if zone and zone.zone == "guests" and zone.email == _user().lower():
            return i18n.t("mcp.guest_zone_deleted", path=path)  # it may be a hidden reply: do not confirm either way
        return i18n.t("mcp.deleted", path=path) if gone else i18n.t("mcp.not_deleted", path=path)

    return mcp


def _transport_security() -> TransportSecuritySettings:
    """Only accept the public host (Caddy passes it through), so DNS rebinding can't reach /mcp."""
    base = urlparse(hub.BASE_URL)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[base.netloc],
        allowed_origins=[f"{base.scheme}://{base.netloc}", "https://claude.ai", "https://claude.com"],
    )


class Connector:
    """ASGI app for the mount. Its session manager runs once per lifespan, so a new one is built for each
    (production has one lifespan; tests start many)."""

    def __init__(self):
        self._build()

    def _build(self) -> None:
        self.mcp = build_mcp()
        self.app = self.mcp.streamable_http_app(
            streamable_http_path="/mcp", stateless_http=True, json_response=True,
            transport_security=_transport_security(), host="0.0.0.0",
        )
        self._used = False

    @asynccontextmanager
    async def lifespan(self, _app):
        if self._used:
            self._build()
        self._used = True
        async with self.mcp.session_manager.run():
            yield

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)
