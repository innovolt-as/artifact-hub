import io
import json
import zipfile

import pytest

from app import versions

HTML = "<!doctype html><title>A</title><p>v1</p>"
HTML2 = "<!doctype html><title>A</title><p>v2</p>"


def test_create_is_private_by_default(hub):
    hub.save_page("ny", "<!doctype html><title>Ny</title>", create=True)
    assert hub._read_meta(hub._meta_path("ny"))["admin_only"] is True


def test_create_can_be_public(hub):
    hub.save_page("ny", HTML, create=True, private=False)
    assert not hub._read_meta(hub._meta_path("ny")).get("admin_only")


def test_create_fails_if_exists(hub):
    hub.save_page("ny", HTML, create=True)
    with pytest.raises(hub.HubError, match="update_app"):
        hub.save_page("ny", HTML, create=True)


def test_create_rejects_bad_slug(hub):
    with pytest.raises(hub.HubError):
        hub.save_page("Ugyldig Navn!", HTML, create=True)


def test_update_fails_if_missing(hub):
    with pytest.raises(hub.HubError):
        hub.save_page("finnes-ikke", HTML, create=False)


def test_update_keeps_meta_and_versions(hub):
    hub.save_page("a", HTML, create=True, title="A", emoji="📈")
    hub.save_page("a", HTML2, create=False)
    meta = hub._read_meta(hub._meta_path("a"))
    assert meta["title"] == "A" and meta["emoji"] == "📈" and meta["admin_only"] is True
    assert "v2" in hub.page_source("a")
    assert len(versions.list_versions(hub.ARTIFACTS_DIR, "a")) == 1


def test_update_can_change_fields(hub):
    hub.save_page("a", HTML, create=True, title="A")
    hub.save_page("a", HTML2, create=False, title="B", description="d", private=False)
    meta = hub._read_meta(hub._meta_path("a"))
    assert meta["title"] == "B" and meta["description"] == "d" and not meta.get("admin_only")


def test_rejects_non_html(hub):
    with pytest.raises(hub.HubError, match="HTML"):
        hub.save_page("x", "export default function App() { return <div/> }", create=True)
    assert hub._meta_path("x") is None


def test_accepts_uppercase_html(hub):
    hub.save_page("x", "<BODY>hei</BODY>", create=True)


def test_rejects_too_large(hub):
    with pytest.raises(hub.HubError):
        hub.save_page("x", "<html>" + "a" * hub.MAX_PAGE_BYTES, create=True)
    assert hub._meta_path("x") is None


def test_update_uploaded_folder_app_but_refuse_link(hub, admin_client, upload):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", HTML)
        z.writestr("sw.js", "// sw")
    upload(admin_client, "mappe.zip", buf.getvalue())
    hub.save_page("mappe", HTML2, create=False)
    assert (hub.ARTIFACTS_DIR / "mappe" / "index.html").read_text() == HTML2
    assert (hub.ARTIFACTS_DIR / "mappe" / "sw.js").read_text() == "// sw"
    assert not (hub.ARTIFACTS_DIR / "mappe.html").exists()
    (hub.ARTIFACTS_DIR / "kort.link.json").write_text(json.dumps({"title": "K", "url": "https://x.no/y"}))
    with pytest.raises(hub.HubError):
        hub.save_page("kort", HTML2, create=False)
    assert (hub.ARTIFACTS_DIR / "kort.link.json").is_file()


def test_edit_page_all_or_nothing(hub):
    hub.save_page("a", "<html><p>en</p><p>to</p></html>", create=True)
    with pytest.raises(hub.HubError, match="2"):  # edit nr. 2 finnes ikke
        hub.edit_page("a", [("en", "EN"), ("tre", "TRE")])
    assert "en" in hub.page_source("a") and "EN" not in hub.page_source("a")
    assert versions.list_versions(hub.ARTIFACTS_DIR, "a") == []


def test_edit_page_applies_and_versions(hub):
    hub.save_page("a", "<html><p>en</p><p>to</p></html>", create=True)
    hub.edit_page("a", [("en", "EN"), ("to", "TO")])
    assert hub.page_source("a") == "<html><p>EN</p><p>TO</p></html>"
    assert len(versions.list_versions(hub.ARTIFACTS_DIR, "a")) == 1


def test_edit_page_ambiguous(hub):
    hub.save_page("a", "<html><p>en</p><p>to</p></html>", create=True)
    with pytest.raises(hub.HubError, match="flere|2 ganger"):
        hub.edit_page("a", [("<p>", "<div>")])
    assert "<div>" not in hub.page_source("a")


def test_edit_page_missing(hub):
    with pytest.raises(hub.HubError):
        hub.edit_page("finnes-ikke", [("a", "b")])


def test_set_info_on_page(hub):
    hub.save_page("a", HTML, create=True, title="A", description="d")
    hub.set_info("a", title="B", description="", private=False)
    meta = hub._read_meta(hub._meta_path("a"))
    assert meta["title"] == "B" and "description" not in meta and not meta.get("admin_only")
    hub.set_info("a", emoji="🔥")
    meta = hub._read_meta(hub._meta_path("a"))
    assert meta["title"] == "B" and meta["emoji"] == "🔥"
    hub.set_info("a", private=True)
    assert hub._read_meta(hub._meta_path("a"))["admin_only"] is True


def test_set_info_on_link_card(hub):
    p = hub.ARTIFACTS_DIR / "kort.link.json"
    p.write_text(json.dumps({"title": "K", "url": "https://x.no/y"}))
    hub.set_info("kort", emoji="🔗")
    meta = json.loads(p.read_text())
    assert meta["emoji"] == "🔗" and meta["url"] == "https://x.no/y" and meta["title"] == "K"


def test_set_info_missing(hub):
    with pytest.raises(hub.HubError):
        hub.set_info("finnes-ikke", title="x")


def test_page_source_has_no_shim(hub, admin_client):
    hub.save_page("a", HTML, create=True)
    assert "hub.js" in admin_client.get("/a/a/").text and "hub.js" not in hub.page_source("a")


def test_served_page_blocks_sideways_scroll(hub, admin_client):
    # iOS zooms in on inputs under 16px and stays zoomed, which leaves the page scrolling sideways
    hub.save_page("a", HTML, create=True)
    served = admin_client.get("/a/a/").text
    assert "overflow-x: clip" in served and "font-size: max(16px, 1em)" in served
    assert "overflow-x" not in hub.page_source("a")


def _folder_app(hub, slug="mappe"):
    d = hub.ARTIFACTS_DIR / slug
    d.mkdir()
    (d / "index.html").write_text(HTML, "utf-8")
    (d / "sw.js").write_text("// service worker", "utf-8")
    (d / "meta.json").write_text(json.dumps({"title": "Mappe", "emoji": "📁"}), "utf-8")
    return d


def test_folder_app_source_is_its_index(hub):
    _folder_app(hub)
    assert hub.page_source("mappe") == HTML


def test_update_folder_app_replaces_index_only(hub):
    d = _folder_app(hub)
    hub.save_page("mappe", HTML2, create=False)
    assert "v2" in (d / "index.html").read_text()
    assert (d / "sw.js").read_text() == "// service worker"
    assert not (hub.ARTIFACTS_DIR / "mappe.html").exists() and not (hub.ARTIFACTS_DIR / "mappe.meta.json").exists()
    meta = hub._read_meta(hub._meta_path("mappe"))
    assert meta["title"] == "Mappe" and meta["emoji"] == "📁" and not meta.get("admin_only")
    saved = versions.list_versions(hub.ARTIFACTS_DIR, "mappe")
    assert len(saved) == 1 and saved[0].suffix == ".zip"
    with zipfile.ZipFile(saved[0]) as z:
        assert z.read("index.html").decode() == HTML and "sw.js" in z.namelist()


def test_edit_folder_app(hub):
    d = _folder_app(hub)
    hub.edit_page("mappe", [("<p>v1</p>", "<p>v3</p>")])
    assert "v3" in (d / "index.html").read_text() and (d / "sw.js").exists()
    assert len(versions.list_versions(hub.ARTIFACTS_DIR, "mappe")) == 1


def test_update_folder_app_can_change_info(hub):
    _folder_app(hub)
    hub.save_page("mappe", HTML2, create=False, title="Ny tittel", private=True)
    meta = hub._read_meta(hub._meta_path("mappe"))
    assert meta["title"] == "Ny tittel" and meta["admin_only"] is True


def test_create_fails_if_folder_app_exists(hub):
    _folder_app(hub)
    with pytest.raises(hub.HubError, match="update_app"):
        hub.save_page("mappe", HTML, create=True)
