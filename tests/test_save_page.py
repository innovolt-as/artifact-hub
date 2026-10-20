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


def test_update_refuses_folder_app_and_link(hub, admin_client, upload):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", HTML)
    upload(admin_client, "mappe.zip", buf.getvalue())
    (hub.ARTIFACTS_DIR / "kort.link.json").write_text(json.dumps({"title": "K", "url": "https://x.no/y"}))
    for slug in ("mappe", "kort"):
        with pytest.raises(hub.HubError):
            hub.save_page(slug, HTML2, create=False)
    assert (hub.ARTIFACTS_DIR / "mappe" / "index.html").read_text() == HTML
    assert (hub.ARTIFACTS_DIR / "kort.link.json").is_file()
    assert not (hub.ARTIFACTS_DIR / "mappe.html").exists()


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
