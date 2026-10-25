from app import main

DEFAULT_LOGO = (main.BASE_DIR / "static" / "logo.svg").read_bytes()


def _brand(name, content=b"<svg>brand</svg>"):
    main.BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    (main.BRANDING_DIR / name).write_bytes(content)


def test_default_logo_without_branding_dir(client):
    assert client.get("/static/logo.svg").content == DEFAULT_LOGO


def test_branding_logo_replaces_default(client):
    _brand("logo.svg")
    r = client.get("/static/logo.svg")
    assert r.status_code == 200 and r.content == b"<svg>brand</svg>"
    assert r.headers["content-type"].startswith("image/svg+xml")


def test_missing_branding_file_falls_back(client):
    _brand("logo.svg")  # only the logo is branded
    assert client.get("/static/favicon-32.png").content == (main.BASE_DIR / "static" / "favicon-32.png").read_bytes()


def test_other_static_names_are_never_overridden(client):
    _brand("hub.js", b"alert(1)")
    assert b"alert(1)" not in client.get("/static/hub.js").content


def test_favicon_ico_uses_branding(client):
    _brand("favicon-32.png", b"PNGBRAND")
    assert client.get("/favicon.ico").content == b"PNGBRAND"
