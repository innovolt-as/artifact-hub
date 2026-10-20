import io
import zipfile

from app import versions


def make_zip(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", body)
    return buf.getvalue()


def test_reupload_saves_previous_version(admin_client, hub, upload):
    upload(admin_client, "a.html", "<html>v1</html>")
    upload(admin_client, "a.html", "<html>v2</html>")
    vs = versions.list_versions(hub.ARTIFACTS_DIR, "a")
    assert len(vs) == 1 and vs[0].read_text() == "<html>v1</html>"


def test_first_upload_saves_nothing(admin_client, hub, upload):
    upload(admin_client, "a.html", "<html>v1</html>")
    assert versions.list_versions(hub.ARTIFACTS_DIR, "a") == []


def test_keeps_only_ten(admin_client, hub, upload):
    for i in range(13):
        upload(admin_client, "a.html", f"<html>v{i}</html>")
    vs = versions.list_versions(hub.ARTIFACTS_DIR, "a")
    assert len(vs) == 10 and vs[-1].read_text() == "<html>v11</html>"


def test_folder_app_versioned_as_zip(admin_client, hub, upload):
    upload(admin_client, "app.zip", make_zip("<html>v1</html>"))
    upload(admin_client, "app.zip", make_zip("<html>v2</html>"))
    vs = versions.list_versions(hub.ARTIFACTS_DIR, "app")
    assert len(vs) == 1 and vs[0].suffix == ".zip"
    with zipfile.ZipFile(vs[0]) as z:
        assert z.read("index.html") == b"<html>v1</html>"


def test_rename_moves_versions(admin_client, hub, upload):
    upload(admin_client, "a.html", "<html>v1</html>")
    upload(admin_client, "a.html", "<html>v2</html>")
    admin_client.post("/api/edit", data={"slug": "a", "new_slug": "b"})
    assert len(versions.list_versions(hub.ARTIFACTS_DIR, "b")) == 1
    assert versions.list_versions(hub.ARTIFACTS_DIR, "a") == []


def test_versions_dir_not_in_gallery(admin_client, upload):
    upload(admin_client, "a.html", "<html>v1</html>")
    upload(admin_client, "a.html", "<html>v2</html>")
    assert ".versions" not in admin_client.get("/").text
