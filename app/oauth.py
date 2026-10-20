"""
OAuth authorization server for the Claude connector (claude.ai "custom connector" -> /mcp).

Only admins (ADMIN_EMAILS) can ever get a token, and load_access_token re-checks that on every call,
so removing someone from ADMIN_EMAILS cuts them off at once. The SDK supplies the HTTP endpoints
(/authorize, /token, /register, /revoke, metadata) and checks PKCE, redirect_uri and code expiry;
this module stores clients/requests/codes/tokens and adds the consent page in between:

    /authorize -> provider.authorize() stores the request -> /oauth/consent?req=...
    -> admin clicks «Gi tilgang» -> redirect_uri?code=...&state=... -> /token

Codes and tokens are stored as SHA-256 hashes only.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app import main as hub

REDIRECT_ALLOWLIST = {"https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"}
REQUEST_TTL = 15 * 60             # a consent request; long enough to log in via magic link first
CODE_TTL = 5 * 60                 # authorization code
ACCESS_TTL = 3600                 # access token
REFRESH_TTL = 90 * 24 * 3600      # refresh token
# browsers must never show the consent page inside someone else's frame (clickjacking)
NO_FRAMES = {"Content-Security-Policy": "frame-ancestors 'none'", "X-Frame-Options": "DENY",
             "Cache-Control": "no-store"}

router = APIRouter()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _scopes(raw: str | None) -> list[str]:
    return raw.split() if raw else []


def _purge(con) -> None:
    now = time.time()
    con.execute("DELETE FROM oauth_requests WHERE expires_at < ?", (now,))
    con.execute("DELETE FROM oauth_codes WHERE expires_at < ?", (now,))
    con.execute("DELETE FROM oauth_tokens WHERE expires_at < ?", (now,))


def _issue(con, client_id: str, email: str, scopes: list[str], resource: str | None,
           refresh_scopes: list[str] | None = None) -> OAuthToken:
    """New access + refresh token pair; only the hashes are stored."""
    _purge(con)
    now = int(time.time())
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    rows = [(_hash(access), "access", " ".join(scopes), now + ACCESS_TTL),
            (_hash(refresh), "refresh", " ".join(refresh_scopes if refresh_scopes is not None else scopes),
             now + REFRESH_TTL)]
    for token_hash, kind, scope, expires_at in rows:
        con.execute(
            "INSERT INTO oauth_tokens(token_hash,kind,client_id,email,scopes,resource,expires_at) VALUES(?,?,?,?,?,?,?)",
            (token_hash, kind, client_id, email, scope, resource, expires_at),
        )
    return OAuthToken(access_token=access, expires_in=ACCESS_TTL, scope=" ".join(scopes) or None,
                      refresh_token=refresh)


class HubOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with hub.db() as con:
            row = con.execute("SELECT info FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row["info"]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in client_info.redirect_uris or []]
        if not uris or any(u not in REDIRECT_ALLOWLIST for u in uris):
            raise RegistrationError("invalid_redirect_uri", "Bare Claude (claude.ai/claude.com) kan kobles til denne huben.")
        with hub.db() as con:
            con.execute("INSERT INTO oauth_clients(client_id, info) VALUES(?,?)",
                        (client_info.client_id, client_info.model_dump_json()))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        req = secrets.token_urlsafe(32)
        with hub.db() as con:
            _purge(con)
            con.execute("INSERT INTO oauth_requests(id, client_id, params, expires_at) VALUES(?,?,?,?)",
                        (req, client.client_id, params.model_dump_json(), int(time.time()) + REQUEST_TTL))
        return f"{hub.BASE_URL}/oauth/consent?req={req}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str
                                      ) -> AuthorizationCode | None:
        with hub.db() as con:
            row = con.execute("SELECT * FROM oauth_codes WHERE code_hash=? AND client_id=? AND expires_at>?",
                              (_hash(authorization_code), client.client_id, time.time())).fetchone()
        if not row:
            return None
        p = AuthorizationParams.model_validate_json(row["params"])
        return AuthorizationCode(
            code=authorization_code, scopes=p.scopes or [], expires_at=row["expires_at"], client_id=row["client_id"],
            code_challenge=p.code_challenge, redirect_uri=p.redirect_uri,
            redirect_uri_provided_explicitly=p.redirect_uri_provided_explicitly, resource=p.resource,
            subject=row["email"],
        )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        row = _spend("oauth_codes", "code_hash", authorization_code.code)
        _check_grant(row, client, "Koden er ugyldig, utløpt eller allerede brukt.")
        with hub.db() as con:
            return _issue(con, client.client_id, row["email"], authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        row = _load_token(refresh_token, "refresh")
        if not row or row["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=row["client_id"], scopes=_scopes(row["scopes"]),
                            expires_at=row["expires_at"], resource=row["resource"], subject=row["email"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        # rotation: the old refresh token is gone the moment it is used
        row = _spend("oauth_tokens", "token_hash", refresh_token.token, "AND kind='refresh'")
        _check_grant(row, client, "Refresh-tokenet er ugyldig, utløpt eller allerede brukt.")
        with hub.db() as con:
            return _issue(con, client.client_id, row["email"], scopes, row["resource"],
                          refresh_scopes=_scopes(row["scopes"]))

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = _load_token(token, "access")
        if not row:
            return None
        return AccessToken(token=token, client_id=row["client_id"], scopes=_scopes(row["scopes"]),
                           expires_at=row["expires_at"], resource=row["resource"], subject=row["email"])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revokes the whole grant: every token this client holds for this user."""
        with hub.db() as con:
            row = con.execute("SELECT client_id, email FROM oauth_tokens WHERE token_hash=?",
                              (_hash(token.token),)).fetchone()
            if row:
                con.execute("DELETE FROM oauth_tokens WHERE client_id=? AND email=?", (row["client_id"], row["email"]))


def _spend(table: str, key: str, secret: str, extra: str = ""):
    """Delete and return the row for a one-time secret, or None. Committed before anything is checked,
    so a code/refresh token can be spent only once, even by two racing requests."""
    h = _hash(secret)
    with hub.db() as con:
        row = con.execute(f"SELECT * FROM {table} WHERE {key}=? {extra}", (h,)).fetchone()
        if not row or con.execute(f"DELETE FROM {table} WHERE {key}=?", (h,)).rowcount != 1:
            return None
    return row


def _check_grant(row, client: OAuthClientInformationFull, message: str) -> None:
    if not row or row["client_id"] != client.client_id or row["expires_at"] < time.time():
        raise TokenError("invalid_grant", message)
    if not hub.is_admin(row["email"]):
        raise TokenError("invalid_grant", "Bare administratorer kan bruke connectoren.")


def _load_token(token: str, kind: str):
    """The unexpired token row, but only while its owner is still an admin (checked on every call)."""
    with hub.db() as con:
        row = con.execute("SELECT * FROM oauth_tokens WHERE token_hash=? AND kind=? AND expires_at>?",
                          (_hash(token), kind, time.time())).fetchone()
    return row if row and hub.is_admin(row["email"]) else None


# ---------------------------------------------------------------- consent page
def _pending_client(req: str) -> OAuthClientInformationFull | None:
    """The client behind an unexpired consent request, or None."""
    with hub.db() as con:
        row = con.execute("SELECT * FROM oauth_requests WHERE id=? AND expires_at>?", (req, time.time())).fetchone()
        info = row and con.execute("SELECT info FROM oauth_clients WHERE client_id=?", (row["client_id"],)).fetchone()
    return OAuthClientInformationFull.model_validate_json(info["info"]) if info else None


def _take(req: str) -> tuple[str, AuthorizationParams] | None:
    """Consume a consent request (single use). Returns (client_id, params) or None if unknown/expired/used."""
    with hub.db() as con:
        row = con.execute("SELECT * FROM oauth_requests WHERE id=?", (req,)).fetchone()
        if not row or con.execute("DELETE FROM oauth_requests WHERE id=?", (req,)).rowcount != 1:
            return None
    if row["expires_at"] < time.time():
        return None
    return row["client_id"], AuthorizationParams.model_validate_json(row["params"])


def _new_code(client_id: str, email: str, params: AuthorizationParams) -> str:
    code = secrets.token_urlsafe(32)
    with hub.db() as con:
        con.execute("INSERT INTO oauth_codes(code_hash, client_id, email, params, expires_at) VALUES(?,?,?,?,?)",
                    (_hash(code), client_id, email, params.model_dump_json(), time.time() + CODE_TTL))
    return code


def _approve(req: str, email: str) -> str | None:
    """Turn a consent request into an authorization code for `email` (caller has checked is_admin)."""
    taken = _take(req)
    return _new_code(taken[0], email, taken[1]) if taken else None


def _page(request: Request, user: str | None, status: int = 200, **ctx) -> HTMLResponse:
    return hub.templates.TemplateResponse(
        request, "consent.html",
        {"site": hub.SITE_NAME, "user": user, "admin": hub.is_admin(user), **ctx},
        status_code=status, headers=NO_FRAMES,
    )


def _gate(request: Request, req: str):
    """None if the logged-in user is an admin; otherwise the response to send instead."""
    user = hub.current_user(request)
    if not user:
        target = f"/oauth/consent?req={quote(req, safe='')}"
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=302)
    if not hub.is_admin(user):
        return _page(request, user, 403, error="Bare administratorer kan koble Claude til denne huben.")
    return None


EXPIRED = "Forespørselen er ugyldig eller utløpt. Start tilkoblingen på nytt fra Claude."


@router.get("/oauth/consent", response_class=HTMLResponse)
def consent_page(request: Request, req: str = ""):
    if refused := _gate(request, req):
        return refused
    user = hub.current_user(request)
    client = _pending_client(req)
    if not client:
        return _page(request, user, 400, error=EXPIRED)
    return _page(request, user, req=req, client_name=client.client_name or client.client_id)


@router.post("/oauth/consent")
def consent_submit(request: Request, req: str = Form(""), decision: str = Form("")):
    if refused := _gate(request, req):
        return refused
    user = hub.current_user(request)
    if decision not in ("allow", "deny"):
        return _page(request, user, 400, error="Ugyldig valg.")
    taken = _take(req)
    # registration already restricts redirect_uris to the allowlist; check again before redirecting
    if not taken or str(taken[1].redirect_uri) not in REDIRECT_ALLOWLIST:
        return _page(request, user, 400, error=EXPIRED)
    client_id, params = taken
    if decision == "allow":
        loc = construct_redirect_uri(str(params.redirect_uri), code=_new_code(client_id, user, params), state=params.state)
    else:
        loc = construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state)
    return RedirectResponse(loc, status_code=303, headers={"Cache-Control": "no-store"})
