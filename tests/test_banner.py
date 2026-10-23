import io
import zipfile

import pytest

from app import banner

APP = {"title": "Matboka", "emoji": "🥗", "icon_url": None, "hue": 120}


# ---------------------------------------------------------------- markup
def test_links_home_with_label():
    out = banner.render(APP, "Innovolt apps")
    assert out.startswith("<hub-banner>") and 'shadowrootmode="open"' in out
    assert 'href="/"' in out and 'aria-label="Tilbake til Innovolt apps"' in out
    assert "history.back" not in out and "<script" not in out


def test_emoji_sits_before_name():
    out = banner.render(APP, "S")
    assert out.index("🥗") < out.index("Matboka")


def test_image_icon_and_letter_fallback():
    assert '<img src="/icon/x?v=1"' in banner.render({**APP, "icon_url": "/icon/x?v=1"}, "S")
    out = banner.render({**APP, "emoji": ""}, "S")
    assert ">M<" in out and "hsl(120" in out


def test_title_and_site_escaped():
    out = banner.render({**APP, "title": '<script>x</script>"&'}, 'A"B')
    assert "<script>x" not in out and "&lt;script&gt;" in out and "&amp;" in out
    assert "Tilbake til A&quot;B" in out


def test_one_line_and_print_hidden():
    out = banner.render(APP, "S")
    assert "white-space:nowrap" in out.replace(" ", "") and "ellipsis" in out
    assert "safe-area-inset-top" in out
    assert "@media print" in banner.CSS_HOST


# ---------------------------------------------------------------- served pages
@pytest.fixture
def zip_bytes():
    def _zip(files: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, text in files.items():
                z.writestr(name, text)
        return buf.getvalue()
    return _zip


def test_banner_after_body(admin_client, upload):
    upload(admin_client, "mat.html", '<!doctype html><html><head><title>Matboka</title></head>'
           '<BODY class="x"><h1>Hei</h1></body></html>', title="Matboka")
    html = admin_client.get("/a/mat/").text
    assert html.index('<BODY class="x">') < html.index("<hub-banner>") < html.index("<h1>Hei")
    assert "hub-banner{all:initial" in html.split("</head>")[0].replace(" ", "")


def test_banner_skips_body_in_comment_before_real_one(admin_client, upload):
    upload(admin_client, "c.html", "<html><head><!-- <body> --><title>C</title></head><body><p>x</p></body></html>")
    html = admin_client.get("/a/c/").text
    assert html.index("<title>C") < html.index("<hub-banner>") < html.index("<p>x")


def test_banner_without_body_tag(admin_client, upload):
    upload(admin_client, "frag.html", "<title>F</title><p>x</p>")
    html = admin_client.get("/a/frag/").text
    assert html.index("hub.js") < html.index("<hub-banner>") < html.index("<p>x")


def test_no_banner_for_fetch_or_iframe(admin_client, upload):
    upload(admin_client, "a.html", "<body><p>x</p></body>")
    for dest in ("empty", "iframe"):
        r = admin_client.get("/a/a/", headers={"Sec-Fetch-Dest": dest})
        assert "<hub-banner>" not in r.text and "hub.js" in r.text
    assert "<hub-banner>" in admin_client.get("/a/a/", headers={"Sec-Fetch-Dest": "document"}).text


def test_banner_off_in_meta(hub, admin_client, upload):
    upload(admin_client, "a.html", "<body><p>x</p></body>")
    p = hub._meta_path("a") or hub.ARTIFACTS_DIR / "a.meta.json"
    m = hub._read_meta(p)
    m["banner"] = False
    hub._write_meta(p, m)
    assert "<hub-banner>" not in admin_client.get("/a/a/").text


def test_banner_on_folder_subpage(admin_client, upload, zip_bytes):
    upload(admin_client, "app.zip", zip_bytes({"index.html": "<body>i</body>", "sub/side.html": "<body>s</body>"}))
    assert "<hub-banner>" in admin_client.get("/a/app/sub/side.html").text


def test_banner_name_for_admin_only_app(admin_client, upload):
    upload(admin_client, "hemmelig.html", "<body>x</body>", title="Hemmelig", admin_only="true")
    assert "Hemmelig" in admin_client.get("/a/hemmelig/").text.split("<hub-banner>")[1]


def test_banner_for_regular_user(admin_client, user_client, upload):
    upload(admin_client, "a.html", "<body>x</body>", title="Delt")
    assert "Delt" in user_client.get("/a/a/").text.split("<hub-banner>")[1]


# ---------------------------------------------------------------- admin switch
def test_toggle_banner(hub, admin_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    r = admin_client.post("/api/toggle-banner", data={"slug": "a"})
    assert r.json() == {"ok": True, "banner": False}
    assert "<hub-banner>" not in admin_client.get("/a/a/").text
    assert admin_client.post("/api/toggle-banner", data={"slug": "a"}).json()["banner"] is True
    assert "banner" not in hub._read_meta(hub._meta_path("a"))
    assert "<hub-banner>" in admin_client.get("/a/a/").text


def test_toggle_banner_rules(admin_client, user_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    assert user_client.post("/api/toggle-banner", data={"slug": "a"}).status_code in (401, 403)
    assert admin_client.post("/api/toggle-banner", data={"slug": "nope"}).status_code == 404
    admin_client.post("/api/link", data={"title": "L", "url": "https://example.com"})
    assert admin_client.post("/api/toggle-banner", data={"slug": "l"}).status_code == 404


def test_banner_off_survives_reupload(hub, admin_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    admin_client.post("/api/toggle-banner", data={"slug": "a"})
    upload(admin_client, "a.html", "<body>y</body>")
    assert hub._read_meta(hub._meta_path("a"))["banner"] is False
    hub.save_page("a", "<!doctype html><body>z</body>", create=False)
    hub.set_info("a", title="Ny")
    assert hub._read_meta(hub._meta_path("a"))["banner"] is False


def test_admin_shows_banner_button_not_on_links(admin_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    admin_client.post("/api/link", data={"title": "L", "url": "https://example.com"})
    page = admin_client.get("/admin").text
    assert page.count('class="small banner"') == 1
