"""SECRET_KEY and UPLOAD_TOKEN: the example values stop the hub, and the upload token is the only way past login."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGE = ("t.html", b"<!doctype html><title>T</title>")


def _import_main(tmp_path, **env):
    """Import app.main in a fresh interpreter, the way the hub starts."""
    full = {**os.environ, "DB_PATH": str(tmp_path / "hub.db"), "ARTIFACTS_DIR": str(tmp_path / "artifacts"), **env}
    full = {k: v for k, v in full.items() if v is not None}
    return subprocess.run([sys.executable, "-c", "import app.main"], cwd=ROOT, env=full,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("name", ["SECRET_KEY", "UPLOAD_TOKEN"])
def test_example_value_stops_the_hub(tmp_path, name):
    r = _import_main(tmp_path, **{name: "change-me-long-random-string"})
    assert r.returncode != 0
    assert f"{name} still has the example value from .env.example" in r.stderr


def test_env_example_secret_key_is_refused(hub, monkeypatch):
    value = re.search(r"^SECRET_KEY=(.*)$", (ROOT / ".env.example").read_text(), re.M)[1]
    monkeypatch.setenv("SECRET_KEY", value)
    with pytest.raises(SystemExit):
        hub._secret("SECRET_KEY")


def test_missing_secret_key_starts_with_a_warning(tmp_path):
    r = _import_main(tmp_path, SECRET_KEY=None)
    assert r.returncode == 0, r.stderr
    assert "SECRET_KEY is not set" in r.stderr


def test_upload_token(hub, client, monkeypatch):
    monkeypatch.setattr(hub, "UPLOAD_TOKEN", "a-long-random-token")
    ok = client.post("/api/upload", files={"file": PAGE}, headers={"Authorization": "Bearer a-long-random-token"})
    assert ok.status_code == 200 and ok.json()["slug"] == "t"
    wrong = client.post("/api/upload", files={"file": PAGE}, headers={"Authorization": "Bearer a-long-random-tokeN"})
    assert wrong.status_code == 302 and wrong.headers["location"].startswith("/login")


def test_no_upload_token_means_no_token_uploads(hub, client, monkeypatch):
    monkeypatch.setattr(hub, "UPLOAD_TOKEN", "")
    r = client.post("/api/upload", files={"file": PAGE}, headers={"Authorization": "Bearer "})
    assert r.status_code == 302
