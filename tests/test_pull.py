"""Pull to refresh (static/pull.js): loaded on the hub's own pages and in every app page."""


def test_pull_js_in_app_pages(admin_client, upload):
    upload(admin_client, "a.html", "<html><head><title>A</title></head><body><p>x</p></body></html>")
    html = admin_client.get("/a/a/").text
    head = html[: html.index("</head>")]
    assert head.index("/static/hub.js") < head.index('<script src="/static/pull.js" defer></script>')


def test_pull_js_on_hub_pages(user_client, client):
    assert '<script src="/static/pull.js" defer></script>' in user_client.get("/").text
    assert '<script src="/static/pull.js" defer></script>' in client.get("/login").text


def test_pull_js_only_as_home_screen_app(client):
    js = client.get("/static/pull.js").text
    assert "navigator.standalone" in js and "display-mode: standalone" in js


def test_pull_moves_content_not_header(client):
    js = client.get("/static/pull.js").text
    assert "data-pull-content" in js and "hubRefresh" in js and "passive: false" in js
    assert "hub-pull-glow" in js and "hubDrag" in js
    assert "navigator.standalone" in js  # still only in the home-screen app
