"""The compose file and Caddyfile carry nothing specific to one installation."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_caddyfile_uses_domain_variable():
    text = (ROOT / "Caddyfile").read_text()
    assert "{$DOMAIN}" in text and "innovolt" not in text


def test_compose_builds_locally_and_requires_domain():
    text = (ROOT / "docker-compose.yml").read_text()
    assert "build: ." in text and "ghcr.io" not in text
    assert re.search(r"DOMAIN: \$\{DOMAIN:\?[^}]*DOMAIN", text)


def test_env_example_is_neutral():
    text = (ROOT / ".env.example").read_text()
    assert "innovolt" not in text.lower() and "martin" not in text.lower()
    for key in ("SITE_NAME", "DOMAIN", "BASE_URL", "SECRET_KEY", "ADMIN_EMAILS", "UPLOAD_TOKEN", "SMTP_HOST", "SMTP_FROM"):
        assert re.search(rf"^{key}=", text, re.M), key
