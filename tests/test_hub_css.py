"""hub.css rules that the browsers in the test suite cannot catch going wrong."""
import hashlib
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "app" / "static" / "hub.css").read_text("utf-8")


def rule(selector: str) -> str:
    return re.search(rf"^\s*{re.escape(selector)} \{{(.*?)\}}", CSS, re.M | re.S).group(1)


@pytest.mark.parametrize("selector", [".sheet-in", "#picker ul", ".view", ".sheet .editor form"])
def test_what_is_in_a_sheet_keeps_its_height(selector):
    # flex: 1 has a basis of 0, and on an iPhone the sheet then collapsed to its padding at the bottom of the screen
    assert "flex: 1 1 auto" in rule(selector)


@pytest.mark.parametrize("selector", [".top", ".topbar"])
def test_every_top_bar_has_the_front_pages_colour(selector):
    assert "background: var(--topbar)" in rule(selector)


def test_the_stylesheet_address_follows_its_content(client):
    digest = hashlib.sha256(CSS.encode("utf-8")).hexdigest()[:8]
    assert f'href="/static/hub.css?v={digest}"' in client.get("/login").text
