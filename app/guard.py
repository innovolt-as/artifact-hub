"""What every request passes before it reaches a route, and what every answer carries.

- A request that changes something (not GET, HEAD or OPTIONS) must come from the hub's own pages. The session cookie
  is SameSite=Lax, which stops other sites but not another site under the same registrable domain (a sibling
  subdomain), so the browser's own word is checked: Sec-Fetch-Site when it is sent, else Origin. A request with
  neither (a script, an old browser) passes as before, and so does one that carries no cookie's authority: a
  bearer token, and the connector's own endpoints (OPEN).
- A body may be at most `max_body` bytes, `max_upload` on the paths in `uploads`. Counted as it is read, so a body
  sent without a length is stopped too.
- `early(scope)` may answer before the body is read (an upload from someone who may not upload).
- Answers get the headers a browser needs to treat the hub's pages carefully (HEADERS), unless the route set its own.
"""
from __future__ import annotations

from urllib.parse import urlsplit

SAFE = ("GET", "HEAD", "OPTIONS")
# The Claude connector: called by Claude's servers or an MCP client with a token, never with the session cookie
OPEN = ("/mcp", "/token", "/register", "/revoke")
HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"SAMEORIGIN",       # the hub's pages and apps are framed by the hub's own pages only
    b"referrer-policy": b"same-origin",      # not no-referrer: a form posted under it says "Origin: null"
}
# An app's own files keep the type the browser works out, as before; a public page may be framed anywhere
AS_BEFORE = ("/a/", "/p/")


class TooBig(Exception):
    pass


def same_origin(headers: dict[bytes, bytes], hosts: set[str]) -> bool:
    """Whether a request with these headers was made by a page of the hub itself (or by no page at all)."""
    site = headers.get(b"sec-fetch-site")
    if site is not None:
        return site in (b"same-origin", b"none")  # none: typed, a bookmark, a home-screen app
    origin = headers.get(b"origin")
    if origin is None:
        return True
    return urlsplit(origin.decode("latin-1")).netloc.lower() in hosts | {headers.get(b"host", b"").decode("latin-1").lower()}


class Guard:
    def __init__(self, app, *, base_url: str, max_body: int, max_upload: int, uploads: tuple[str, ...] = (), early=None):
        self.app = app
        self.hosts = {urlsplit(base_url).netloc.lower()}
        self.https = base_url.startswith("https://")
        self.max_body, self.max_upload, self.uploads, self.early = max_body, max_upload, uploads, early

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        headers = dict(scope["headers"])
        started = False

        async def send_headers(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                have = {k.lower() for k, _ in message["headers"]}
                extra = {} if path.startswith(AS_BEFORE) else dict(HEADERS)
                if self.https:
                    extra[b"strict-transport-security"] = b"max-age=31536000"
                message = {**message, "headers": [*message["headers"], *((k, v) for k, v in extra.items() if k not in have)]}
            await send(message)

        async def refuse(status: int, text: bytes, extra: list | None = None):
            await send_headers({"type": "http.response.start", "status": status, "headers": [
                (b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(text)).encode()),
                *(extra or [])]})
            await send({"type": "http.response.body", "body": text})

        if method in SAFE:
            return await self.app(scope, receive, send_headers)
        open_path = path in OPEN or path.startswith("/mcp/")
        bearer = headers.get(b"authorization", b"").lower().startswith(b"bearer ")
        if not (open_path or bearer) and not same_origin(headers, self.hosts):
            return await refuse(403, b"Cross-site request refused")
        limit = self.max_upload if path in self.uploads else self.max_body
        try:
            if int(headers.get(b"content-length", b"0")) > limit:
                return await refuse(413, b"Request body too large")
        except ValueError:
            return await refuse(400, b"Bad Content-Length")
        if self.early:
            answer = self.early(scope)
            if answer:
                status, extra = answer
                return await refuse(status, b"", extra)
        read = 0

        async def counted():
            nonlocal read
            message = await receive()
            if message["type"] == "http.request":
                read += len(message.get("body", b""))
                if read > limit:
                    raise TooBig
            return message

        try:
            await self.app(scope, counted, send_headers)
        except TooBig:
            if not started:
                await refuse(413, b"Request body too large")
