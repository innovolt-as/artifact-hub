"""The public page (/p/<token>/): an app's page for people who are not logged in."""
import pytest

from tests.test_share_links import U, share, token_of
from tests.test_shared_data import make_shared

FOLDER = "<!doctype html><html><head><title>f</title></head><body>folder</body></html>"


@pytest.fixture
def link(hub, make_page, user_client):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True, public_read=["menu"])
    return token_of(share(user_client, title="Jul"))


def make_folder(hub, token_user=U):
    d = hub.ARTIFACTS_DIR / "mappe"
    d.mkdir()
    (d / "index.html").write_text(FOLDER, "utf-8")
    (d / "style.css").write_text("body{}", "utf-8")
    (d / "meta.json").write_text('{"data": "shared", "public": true}', "utf-8")
    return d


def test_public_page_needs_no_login(client, link):
    r = client.get(f"/p/{link}/", headers={"sec-fetch-dest": "document"})
    assert r.status_code == 200
    assert 'data-guest="1"' in r.text and f'data-token="{link}"' in r.text
    assert 'data-share-name="jul"' in r.text and 'data-public-read="menu"' in r.text
    assert U not in r.text and "data-user" not in r.text and "data-admin" not in r.text
    assert "pull.js" not in r.text and "data-lock" not in r.text and "data-offline" not in r.text
    assert "<hub-banner>" in r.text


def test_redirect_to_slash(client, link):
    r = client.get(f"/p/{link}")
    assert r.status_code == 301 and r.headers["location"] == f"/p/{link}/"


def test_headers(client, link):
    r = client.get(f"/p/{link}/")
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"


def test_unknown_token_is_404(hub, client, user_client, link):
    assert client.get("/p/nope/").status_code == 404
    assert client.get("/p/nope/_icon").status_code == 404
    hub.set_public("radar", public=False)
    assert client.get(f"/p/{link}/").status_code == 404
    hub.set_public("radar", public=True)
    assert client.get(f"/p/{link}/").status_code == 200
    share(user_client, action="off")
    assert client.get(f"/p/{link}/").status_code == 404


def test_owner_is_sent_to_the_app(user_client, link):
    r = user_client.get(f"/p/{link}/")
    assert r.status_code == 302 and r.headers["location"] == "/a/radar/"


def test_other_logged_in_user_gets_guest_page(admin_client, link):
    r = admin_client.get(f"/p/{link}/")
    assert r.status_code == 200 and 'data-guest="1"' in r.text
    assert "data-user" not in r.text and "admin@test.no" not in r.text


def test_locked_app_still_opens_by_link(client, link):
    from tests.conftest import lock
    lock(U, "radar")
    r = client.get(f"/p/{link}/")
    assert r.status_code == 200 and "data-lock" not in r.text


def test_guest_banner_has_no_link_home(client, link):
    out = client.get(f"/p/{link}/").text.split("<hub-banner>")[1].split("</hub-banner>")[0]
    assert 'href="/"' not in out and "‹" not in out and 'class="share"' not in out
    assert "radar" in out


def test_guest_icon_comes_from_the_link(hub, client, link):
    (hub.ICONS_DIR).mkdir(exist_ok=True)
    (hub.ICONS_DIR / "radar.png").write_bytes(b"\x89PNG")
    out = client.get(f"/p/{link}/").text
    assert f'src="/p/{link}/_icon' in out and "/icon/radar" not in out
    r = client.get(f"/p/{link}/_icon")
    assert r.status_code == 200 and r.content == b"\x89PNG"
    assert r.headers["x-robots-tag"] == "noindex, nofollow" and "content-security-policy" in r.headers


def test_folder_app_files(hub, client, user_client, link):
    make_folder(hub)
    t = token_of(share(user_client, slug="mappe"))
    r = client.get(f"/p/{t}/style.css")
    assert r.status_code == 200 and r.headers["x-robots-tag"] == "noindex, nofollow"
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    assert "folder" in client.get(f"/p/{t}/").text
    assert client.get(f"/p/{t}/meta.json").status_code == 404
    assert client.get(f"/p/{t}/..%2fradar.html").status_code == 404
    assert client.get(f"/p/{t}/%2e%2e/radar.html").status_code == 404
    assert client.get(f"/p/{link}/style.css").status_code == 404  # a single page has only its front


def test_folder_app_files_by_link_while_the_owner_has_it_locked(hub, client, user_client, link):
    from tests.conftest import lock
    make_folder(hub)
    t = token_of(share(user_client, slug="mappe"))
    lock(U, "mappe")
    r = client.get(f"/p/{t}/style.css")
    assert r.status_code == 200 and r.text == "body{}"
    assert "folder" in client.get(f"/p/{t}/").text
    # the owner's own session still meets the lock
    r = user_client.get("/a/mappe/style.css", headers={"sec-fetch-dest": "style"})
    assert r.status_code == 423 and "body{}" not in r.text
    assert user_client.get("/a/mappe/style.css").status_code == 423


def test_no_visit_logged(hub, client, admin_client, link):
    client.get(f"/p/{link}/")
    admin_client.get(f"/p/{link}/")
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0


def test_owner_tag_has_data_public(user_client, link):
    r = user_client.get("/a/radar/")
    assert 'data-public="1"' in r.text and 'data-public-read="menu"' in r.text
    assert 'class="share"' in r.text.split("<hub-banner>")[1].split("</hub-banner>")[0]


def test_app_without_public_is_unchanged(hub, make_page, user_client):
    make_page("plain")
    r = user_client.get("/a/plain/")
    assert "data-public" not in r.text and 'class="share"' not in r.text
