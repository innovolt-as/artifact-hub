"""Admin page, statistics, access labels and admin/upload error details, in English (and a few nb strings)."""
import io
import json

from app import access, main
from tests.textutil import assert_no_norwegian


def test_access_labels_en(english):
    assert access.describe({}) == "everyone"
    assert access.describe({"admin_only": True}) == "only me"
    assert access.label({"admin_only": True}) == "🔒 Only me"
    assert access.label({}) == "🌍 Everyone"
    assert access.describe({"access": "people", "people": ["a@x.no", "b@x.no"]}) == "2 people"
    assert access.describe({"access": "people", "people": ["a@x.no"]}) == "1 person"


def test_access_labels_nb():
    assert access.label({}) == "🌍 Alle"
    assert access.describe({"admin_only": True}) == "bare meg"
    assert access.describe({"access": "people", "people": ["a@x.no", "b@x.no"]}) == "2 personer"


def test_set_level_error_en(english):
    try:
        access.set_level({}, "nope")
    except ValueError as e:
        assert str(e) == "Unknown access: nope"
    else:
        raise AssertionError("no ValueError")


def test_ago_en(english):
    assert main._ago(1000, 1300) == "5 min ago"
    assert main._ago(0, 3 * 3600) == "3 h ago"
    assert main._ago(0, 2 * 86400) == "2 d ago"


def test_ago_nb():
    assert main._ago(1000, 1300) == "for 5 min siden"
    assert main._ago(0, 3 * 3600) == "for 3 t siden"
    assert main._ago(0, 2 * 86400) == "for 2 d siden"


def test_admin_pages_en(hub, make_page, admin_client, english, pw_mode):
    make_page("p")
    admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "temporary-pw-1"})
    admin_client.get("/a/p/")
    for path in ("/admin", "/admin/stats"):
        r = admin_client.get(path)
        assert r.status_code == 200
        assert_no_norwegian(r.text)
    body = admin_client.get("/admin").text
    assert "Upload" in body and "password: must be changed" in body
    assert "Delete" in body and "Everyone" in body


def test_admin_stats_en_with_data(hub, make_page, user_client, admin_client, english):
    make_page("p")
    user_client.get("/a/p/")
    body = admin_client.get("/admin/stats").text
    assert_no_norwegian(body)
    assert "Last 7 days" in body


def test_admin_confirm_texts_nb(admin_client):
    body = admin_client.get("/admin").text
    assert 'Slette \\"{slug}\\"?' in body  # inside a JS string
    assert "Personen kan ikke logge inn lenger og tas av alle appene." in body


def test_admin_confirm_texts_en(admin_client, english):
    body = admin_client.get("/admin").text
    assert 'Delete \\"{slug}\\"?' in body
    assert "The person can no longer log in and is removed from all apps." in body


def _detail(r):
    return r.json()["detail"]


def test_admin_api_error_en(hub, make_page, admin_client, english):
    make_page("p")
    r = admin_client.post("/api/access", json={"slug": "p", "level": "nope", "people": []})
    assert r.status_code == 400 and _detail(r) == "Unknown access: nope"
    r = admin_client.post("/api/access", json={"slug": "p", "level": "people", "people": "x"})
    assert _detail(r) == "people must be a list of e-mails"
    r = admin_client.post("/api/access", json={"slug": "p", "level": "people", "people": ["bad"]})
    assert _detail(r) == "Invalid e-mail: bad"
    assert _detail(admin_client.post("/api/people/invite", json={"email": "x"})) == "Invalid e-mail"
    assert _detail(admin_client.post("/api/people/invite", json={"email": "admin@test.no"})) == "Admins always have access"
    assert _detail(admin_client.post("/api/people/remove", json={"email": "who@test.no"})) == "Not invited"
    assert _detail(admin_client.post("/api/people/password", json={"email": "who@test.no", "password": "x" * 12})) == "Not in use"


def test_admin_api_error_pw_en(hub, admin_client, english, pw_mode):
    r = admin_client.post("/api/people/invite", json={"email": "n@test.no", "password": "short"})
    assert _detail(r) == "Temporary password must be 10–200 characters"
    r = admin_client.post("/api/people/password", json={"email": "n@test.no", "password": "x" * 12})
    assert _detail(r) == "Not invited"


def test_link_and_edit_errors_en(hub, make_page, admin_client, english):
    make_page("p")
    post = admin_client.post
    assert _detail(post("/api/link", data={"title": "T", "url": "nope"})) == "URL must start with https:// and be a valid address"
    assert _detail(post("/api/link", data={"title": "  ", "url": "https://x.no/"})) == "The link needs a name"
    assert _detail(post("/api/link", data={"title": "p", "url": "https://x.no/"})) == 'There is already something called "p"'
    assert _detail(post("/api/edit", data={"slug": "p"}, files={"icon": ("a.txt", b"x")})) == "The icon must be PNG, JPG, WebP, GIF or SVG"
    big = b"x" * (main.MAX_ICON_BYTES + 1)
    assert _detail(post("/api/edit", data={"slug": "p"}, files={"icon": ("a.png", big)})) == "The icon can be 2 MB at most"
    make_page("q")
    assert _detail(post("/api/edit", data={"slug": "p", "new_slug": "q"})) == "The address /a/q/ is already in use"


def test_upload_errors_en(hub, admin_client, english):
    up = lambda name, data: admin_client.post("/api/upload", files={"file": (name, io.BytesIO(data))})
    assert _detail(up("x.txt", b"x")) == "Only .html or .zip (with index.html) is supported"
    assert _detail(up("x.zip", _zip({"readme.txt": b"x"}))) == "The zip must contain an index.html"
    assert _detail(up("x.zip", _zip({"../evil.txt": b"x"}))) == "The zip contains invalid paths"


def _zip(files):
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()
