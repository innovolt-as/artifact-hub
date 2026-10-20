"""The Claude connector: a remote MCP server at /mcp with tools to list, read, create and change apps.

Mounted on "/" at the bottom of app.main, after every FastAPI route, so it only sees /mcp and the
OAuth endpoints the SDK adds (/authorize, /token, /register, /revoke, /.well-known/...).
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import AnyHttpUrl, BaseModel, Field

from app import main as hub
from app.oauth import HubOAuthProvider

INSTRUCTIONS = f"""\
Publish and maintain single-file HTML apps on {hub.SITE_NAME} ({hub.BASE_URL}).
Use list_apps to find an app's slug. Use create_app only for a brand-new app; new apps are private
(only admins see them) until the user asks to share them. Before update_app or edit_app, call get_app
unless the app's current source is already in the conversation. Prefer edit_app for small changes.
Only publish or change apps when the user explicitly asks you to."""


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
        raise hub.HubError("Bare administratorer kan bruke denne koblingen.")
    return email


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
        description="List every app and link card on the hub, with slug, title, description, URL, whether it is "
        "private, and whether it is editable (only single-file pages are). Use this to find the slug of an "
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
                "private": a["admin_only"],
                "editable": a["kind"] == "page",
            }
            for a in hub.list_artifacts(user)
        ]
        return json.dumps(apps, ensure_ascii=False, indent=1)

    @mcp.tool(
        name="get_app",
        title="Get app source",
        description="Return the current HTML source of a single-file app. Call this before update_app or edit_app "
        "unless the app's current source is already in the conversation. Use list_apps to find the slug.",
        annotations=ToolAnnotations(readOnlyHint=True),
        structured_output=False,
    )
    def get_app(slug: str) -> str:
        try:
            _user()
            return hub.page_source(slug)
        except hub.HubError as e:
            return _error(str(e))

    @mcp.tool(
        name="create_app",
        title="Create app",
        description="Publish a NEW single-file HTML app (a complete HTML document, max 1 MB) at /a/<slug>/. "
        "Only for apps that do not exist yet; it fails if the slug is taken (use list_apps to check, and "
        "update_app or edit_app to change an existing app). New apps are private (only admins see them) "
        "unless private=false; leave them private until the user explicitly asks to share them. "
        "Only call this when the user explicitly asks to publish. "
        "slug: lowercase letters, digits, '.', '-', '_'. emoji: one emoji used as the gallery icon.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
        structured_output=False,
    )
    def create_app(slug: str, html: str, title: str, description: str | None = None, emoji: str | None = None,
                   private: bool = True) -> str:
        try:
            _user()
            hub.save_page(slug, html, create=True, title=title, description=description, emoji=emoji,
                          private=private)
        except hub.HubError as e:
            return _error(str(e))
        return f"Opprettet {'privat ' if private else ''}app: {_url(slug)}"

    @mcp.tool(
        name="update_app",
        title="Replace app",
        description="Replace the whole HTML of an EXISTING single-file app (max 1 MB); the previous version is "
        "kept. Fails if the slug does not exist; does not work on folder apps or link cards. Use list_apps to "
        "find the slug and call get_app first unless the current source is already in the conversation. "
        "For small changes prefer edit_app. Fields left out (title, description, emoji, private) stay as "
        "they are. Only call this when the user explicitly asks to publish the change.",
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
        return f"Oppdatert: {_url(slug)}"

    @mcp.tool(
        name="edit_app",
        title="Edit app",
        description="Make small changes to an EXISTING single-file app by replacing exact snippets of its HTML. "
        "Each 'old' must match the current source exactly once; either all edits apply or none do. "
        "Prefer this over update_app for small changes. Call get_app first unless the current source is "
        "already in the conversation; use list_apps to find the slug. Does not work on folder apps or link "
        "cards. Only call this when the user explicitly asks to publish the change.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
        structured_output=False,
    )
    def edit_app(slug: str, edits: list[Edit]) -> str:
        try:
            _user()
            if not edits:
                raise hub.HubError("Ingen endringer oppgitt.")
            hub.edit_page(slug, [(e.old, e.new) for e in edits])
        except hub.HubError as e:
            return _error(str(e))
        return f"Endret ({len(edits)} endringer): {_url(slug)}"

    @mcp.tool(
        name="update_app_info",
        title="Change app info",
        description="Change the gallery info of an existing app or link card without touching its HTML: title, "
        "description, emoji, or private. Fields left out stay as they are; an empty string removes the field. "
        "private=false shares the app with everyone who can log in: only do that when the user explicitly "
        "asks. Use list_apps to find the slug.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
        structured_output=False,
    )
    def update_app_info(slug: str, title: str | None = None, description: str | None = None,
                        emoji: str | None = None, private: bool | None = None) -> str:
        try:
            _user()
            hub.set_info(slug, title=title, description=description, emoji=emoji, private=private)
        except hub.HubError as e:
            return _error(str(e))
        return f"Oppdatert info for «{slug}»."

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
