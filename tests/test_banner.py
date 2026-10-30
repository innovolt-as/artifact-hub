import io
import zipfile

import pytest

from app import banner

APP = {"title": "Matboka", "emoji": "🥗", "icon_url": None, "hue": 120}


# ---------------------------------------------------------------- markup
def test_links_home_with_label():
    out = banner.render(APP, "My apps")
    assert out.startswith("<hub-banner>") and 'shadowrootmode="open"' in out
    assert 'href="/"' in out and 'aria-label="Tilbake til My apps"' in out
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
    assert "safe-area-inset-top" in banner.CSS_HOST
    assert "@media print" in banner.CSS_HOST


def _rule(css: str, selector: str) -> str:
    """The declarations of the first `selector{...}` rule in css, spaces removed."""
    css = css.replace(" ", "").replace("\n", "")
    start = css.index(selector + "{") + len(selector) + 1
    return css[start:css.index("}", start)]


def test_host_look_is_important_so_the_reset_cannot_wipe_it():
    # all:initial !important on the host beats normal :host rules, so the look must be set there too
    host = _rule(banner.CSS_HOST, "hub-banner")
    for decl in ("background:", "color:#f3f6fb", "font:", "padding-top:env(safe-area-inset-top)"):
        assert decl in host, decl
    assert host.count("!important") >= 8


def test_banner_spans_full_width_inside_padded_body():
    assert "calc(50%-50vw)" in _rule(banner.CSS_HOST, "hub-banner")


def test_icon_box_grows_for_two_emoji():
    ico = _rule(banner.render(APP, "S"), ".ico")
    assert "min-width:18px" in ico and "width:18px" not in ico.replace("min-width:18px", "")


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


# ---------------------------------------------------------------- final review fixes
def test_body_inside_style_title_or_textarea_is_skipped(admin_client, upload):
    upload(admin_client, "s.html", "<html><head><style>/* <body> */ p{color:red}</style><title>a <BODY> b</title></head>"
           "<body><textarea><body></textarea><p>x</p></body></html>")
    html = admin_client.get("/a/s/").text
    assert html.index("</title>") < html.index("<hub-banner>") < html.index("<textarea>")


def test_header_is_not_mistaken_for_head(admin_client, upload):
    upload(admin_client, "h.html", "<!doctype html><html><body><header>H</header><p>x</p></body></html>")
    html = admin_client.get("/a/h/").text
    assert html.index("hub.js") < html.index("<body>") < html.index("<hub-banner>") < html.index("<header>")


def test_banner_moves_itself_out_of_body_and_up(admin_client, upload):
    # body flex/grid layouts and padding above it (e.g. :root safe-area padding) must not move the banner
    upload(admin_client, "a.html", "<body><p>x</p></body>")
    after = admin_client.get("/a/a/").text.split("</hub-banner>")[1]
    script = after[: after.index("</script>")]
    assert after.startswith("<script>") and "insertBefore" in script and "document.body" in script
    assert "margin-top" in script and "resize" in script


def test_inject_is_usable_on_its_own():
    out = banner.inject("<html><head></head><body><p>x</p></body></html>", "<!--head-->", banner.render(APP, "S"))
    assert out.index("<!--head-->") < out.index("<body>") < out.index("<hub-banner>") < out.index("<p>x")
    assert banner.inject("<body>x</body>", "<!--head-->", None) == "<!--head--><body>x</body>"


# ---------------------------------------------------------------- fixed banner and glow hook
def test_fixed_markup():
    html = banner.inject("<html><head></head><body><p>x</p></body></html>", "<h>", banner.render(APP, "S"))
    assert "data-fixed" in html and "hub-banner-space" in html and "--hub-banner-h" in html


def test_css_has_fixed_glow_and_print_rules():
    css = banner.CSS_HOST.replace(" ", "")
    assert "hub-banner[data-fixed]{" in css and "position:fixed!important" in css
    assert "hub-banner-space" in css and 'data-glow="ok"' in banner.CSS_HOST
    assert "@mediaprint{hub-banner,hub-banner-space{display:none" in css


def test_glow_values_and_stacking():
    css = banner.CSS_HOST.replace(" ", "")
    assert "#3fd39c" in css and "#e5484d" in css and "900ms" in css and ".35" in css
    assert 'data-glow="fail"' in css
    z = int(css.split("z-index:")[1].split("!")[0])
    assert z > 10  # above the apps' body::before safe-area strip


def test_app_page_gets_fixed_banner(admin_client, upload):
    upload(admin_client, "a.html", "<html><head><title>A</title></head><body><p>x</p></body></html>")
    assert "data-fixed" in admin_client.get("/a/a/").text


def test_anchors_land_under_the_fixed_banner():
    # zero specificity and not !important, so an app's own scroll-padding-top wins; 0 without the banner
    assert ":where(html){scroll-padding-top:var(--hub-banner-h,0px)}" in banner.CSS_HOST.replace(" ", "")
