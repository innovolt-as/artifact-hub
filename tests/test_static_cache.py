"""Scripts and the stylesheet must never be kept from before an upgrade: /static sent no Cache-Control, so Safari
reused old copies on its own (heuristic caching), and a new page ran with an old home.js."""
import hashlib
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def _digest(name: str) -> str:
    return hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:8]


def _static_refs(html: str) -> list[str]:
    return re.findall(r'(?:src|href)="(/static/[^"]+\.(?:js|css)[^"]*)"', html)


@pytest.mark.parametrize("path", ["/", "/settings", "/admin", "/admin/upload", "/admin/people"])
def test_hub_pages_name_each_script_by_its_content(admin_client, path):
    refs = _static_refs(admin_client.get(path).text)
    assert refs, path
    for ref in refs:
        name, _, query = ref[len("/static/"):].partition("?v=")
        assert query == _digest(name), ref


def test_logged_out_pages_too(client):
    refs = _static_refs(client.get("/login").text)
    assert any("forget.js" in r for r in refs)
    for ref in refs:
        name, _, query = ref[len("/static/"):].partition("?v=")
        assert query == _digest(name), ref


def test_unversioned_static_is_revalidated(client):
    # hub.js and pull.js are injected into apps by those exact addresses (apps look hub.js up by its src)
    for name in ("hub.js", "pull.js", "home.js"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache", name


def test_versioned_static_is_kept(client):
    r = client.get(f"/static/home.js?v={_digest('home.js')}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_apps_keep_the_hub_script_address(admin_client, upload):
    upload(admin_client, "a.html", "<html><head><title>A</title></head><body>x</body></html>")
    html = admin_client.get("/a/a/").text
    assert '<script src="/static/hub.js" ' in html
