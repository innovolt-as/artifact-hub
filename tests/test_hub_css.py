"""hub.css rules that the browsers in the test suite cannot catch going wrong."""
import hashlib
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "app" / "static" / "hub.css").read_text("utf-8")


def rule(selector: str) -> str:
    return re.search(rf"^\s*{re.escape(selector)} \{{(.*?)\}}", CSS, re.M | re.S).group(1)


@pytest.mark.parametrize("selector", [".sheet-in", "#picker .picklist", ".view", ".sheet .editor form"])
def test_what_is_in_a_sheet_keeps_its_height(selector):
    # flex: 1 has a basis of 0, and on an iPhone the sheet then collapsed to its padding at the bottom of the screen
    assert "flex: 1 1 auto" in rule(selector)


@pytest.mark.parametrize("selector", [".top", ".topbar"])
def test_every_top_bar_has_the_front_pages_colour(selector):
    assert "background: var(--topbar)" in rule(selector)


def test_the_stylesheet_address_follows_its_content(client):
    digest = hashlib.sha256(CSS.encode("utf-8")).hexdigest()[:8]
    assert f'href="/static/hub.css?v={digest}"' in client.get("/login").text


def test_a_switch_shows_on_a_phone_without_color_mix():
    # Safari before 16.2 and Chrome before 111 drop the color-mix line, and the switch would have no track when off
    assert re.search(r"background: var\(--line\); background: color-mix", rule(".sw"))


def test_a_hidden_list_stays_hidden():
    # .cards sets display: grid, which beats the hidden attribute of a closed section's list
    assert "display: none" in rule(".apps ul[hidden]")


def test_chevron_rule_is_scoped():
    # the front page's border-drawn chevron must not reach the admin rows' text chevron
    bare = [m.group(1) for m in re.finditer(r"^\s*\.chev \{(.*?)\}", CSS, re.M | re.S)]
    assert not any("border:" in b or "transform" in b for b in bare)
    assert "border:" in rule(".gtoggle .chev") and "rotate" in rule(".gtoggle .chev")
    assert "rotate" in rule('.gtoggle[aria-expanded="true"] .chev')
