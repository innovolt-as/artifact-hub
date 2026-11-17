"""app/guard.py: requests that change something must come from the hub's own pages, bodies have a size limit, an
upload is refused before its body is read, and answers carry the headers that make a browser careful."""
import pytest

from tests.conftest import make_client

HUB = "https://hub.test"


@pytest.mark.parametrize("headers", [
    {"sec-fetch-site": "same-site", "origin": HUB},          # a sibling subdomain; the browser's word beats Origin
    {"sec-fetch-site": "cross-site"},
    {"origin": "https://evil.hub.test"},
    {"origin": "https://hub.test.evil.example"},
    {"origin": "null"},
])
def test_requests_from_other_sites_are_refused(admin_client, make_page, headers):
    make_page("p")
    r = admin_client.post("/api/delete", data={"slug": "p"}, headers=headers)
    assert r.status_code == 403
    assert admin_client.get("/a/p/").status_code == 200  # still there
    assert admin_client.put("/api/store/p/d?path=a/b", json={"x": 1}, headers=headers).status_code == 403
    assert admin_client.post("/logout", headers=headers).status_code == 403


@pytest.mark.parametrize("headers", [
    {}, {"sec-fetch-site": "same-origin"}, {"sec-fetch-site": "none"}, {"origin": HUB},
    {"sec-fetch-site": "same-origin", "origin": "null"},     # a form posted under Referrer-Policy: no-referrer
])
def test_the_hubs_own_pages_and_scripts_pass(admin_client, make_page, headers):
    make_page("p")
    assert admin_client.put("/api/store/p/d?path=a/b", json={"x": 1}, headers=headers).status_code == 200


def test_reading_is_never_refused(admin_client, make_page):
    make_page("p")
    assert admin_client.get("/a/p/", headers={"sec-fetch-site": "cross-site", "sec-fetch-dest": "document"}).status_code == 200


def test_a_token_and_the_connector_are_not_cookie_requests(hub, client, monkeypatch):
    monkeypatch.setattr(hub, "UPLOAD_TOKEN", "t" * 40)
    cross = {"origin": "https://claude.ai", "sec-fetch-site": "cross-site"}
    r = client.post("/api/upload", files={"file": ("a.html", b"<html><body>x</body></html>")},
                    headers={**cross, "authorization": "Bearer " + "t" * 40})
    assert r.status_code == 200
    assert client.post("/register", json={}, headers=cross).status_code != 403


def test_upload_is_refused_before_its_body_is_read(hub, client, user_client, monkeypatch):
    read = []
    monkeypatch.setattr(hub, "_save_upload", lambda *a, **k: read.append(1))
    files = {"file": ("a.html", b"<html><body>x</body></html>")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 302 and r.headers["location"].startswith("/login")  # as the route itself answers
    assert user_client.post("/api/upload", files=files).status_code == 403
    assert read == []


def test_body_limits(hub, admin_client, make_page, monkeypatch):
    make_page("p")
    guard = next(m for m in hub.app.user_middleware if m.cls is hub.guard.Guard)
    assert guard.kwargs["max_body"] == hub.MAX_BODY_BYTES and guard.kwargs["uploads"] == ("/api/upload",)
    monkeypatch.setitem(guard.kwargs, "max_body", 1000)
    monkeypatch.setattr(hub.app, "middleware_stack", None)  # built again with the small limit
    c = make_client("admin@test.no")
    assert c.put("/api/store/p/d?path=a/b", json={"x": "y" * 2000}).status_code == 413
    # a body sent without a length is counted as it comes
    r = c.put("/api/store/p/d?path=a/b", content=iter([b'{"x": "', b"y" * 2000, b'"}']))
    assert r.status_code in (400, 413)
    assert c.get("/api/store/p/d?path=a/b").json() == {"data": None}
    assert c.put("/api/store/p/d?path=a/b", json={"x": 1}).status_code == 200
    monkeypatch.undo()
    hub.app.middleware_stack = None


def test_answers_carry_the_careful_headers(admin_client, client, make_page):
    make_page("p")
    for c, path in ((client, "/login"), (admin_client, "/"), (admin_client, "/settings"), (admin_client, "/admin")):
        h = c.get(path).headers
        assert h["x-content-type-options"] == "nosniff", path
        assert h["x-frame-options"] == "SAMEORIGIN", path
        assert h["referrer-policy"] == "same-origin", path
        assert h["strict-transport-security"] == "max-age=31536000", path
    h = admin_client.get("/a/p/").headers  # an app's files keep the types the browser works out
    assert "x-content-type-options" not in h and "x-frame-options" not in h
    assert "strict-transport-security" in h
