"""Shared fixtures. app.main reads its config at import time, so set the env first."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="hub-test-"))
os.environ.update(
    ARTIFACTS_DIR=str(_tmp / "artifacts"),
    DB_PATH=str(_tmp / "hub.db"),
    ADMIN_EMAILS="admin@test.no",
    ALLOWED_EMAILS="user@test.no",
    BASE_URL="https://hub.test",
    SECRET_KEY="test",
)
os.environ.pop("UPLOAD_TOKEN", None)
os.environ.pop("ALLOWED_DOMAINS", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    """Empty the artifacts dir and the DB tables before each test."""
    for p in main.ARTIFACTS_DIR.iterdir():
        if p.is_dir():
            main.shutil.rmtree(p)
        else:
            p.unlink()
    with main.db() as con:
        for table in ("magic_tokens", "logins", "docs", "app_data"):
            con.execute(f"DELETE FROM {table}")
    main._ip_sends.clear()
    yield


@pytest.fixture
def hub():
    return main


def make_client(email: str | None = None) -> TestClient:
    """A TestClient (https, so the secure cookie is sent), logged in as `email` if given."""
    c = TestClient(main.app, base_url="https://hub.test", follow_redirects=False)
    if email:
        c.cookies.set(main.COOKIE, main.signer.dumps({"email": email}))
    return c


@pytest.fixture
def client():
    return make_client()


@pytest.fixture
def admin_client():
    return make_client("admin@test.no")


@pytest.fixture
def user_client():
    return make_client("user@test.no")


@pytest.fixture
def upload():
    def _upload(client, name, content, **form):
        data = content.encode() if isinstance(content, str) else content
        r = client.post("/api/upload", files={"file": (name, data)}, data=form)
        assert r.status_code == 200, r.text
        return r
    return _upload
