"""A locked app never shows its card line on the front page, not even while it is unlocked."""
import json

import pytest

from tests.conftest import lock, unlock

USER = "user@test.no"
RECIPE = "<script data-hub-card>function hubCard() { return 'SECRET LINE'; }</script>"


def _page(hub, slug, recipe=""):
    hub.save_page(slug, f"<!doctype html><html><head><title>{slug}</title></head><body>{recipe}</body></html>",
                  create=True, private=False)
    meta = hub._meta_path(slug)
    hub._write_meta(meta, {**hub._read_meta(meta), "description": f"about {slug}"})
    with hub.db() as con:
        hub.home.set_added(con, USER, slug, True)


def _item(html, slug):
    return html.split(f'data-slug="{slug}"')[1].split("</li>")[0]


@pytest.fixture
def cards(hub):
    """A recipe app `mat` and an app `ovn` with a stored line; both in card view."""
    _page(hub, "mat", RECIPE)
    _page(hub, "ovn")
    with hub.db() as con:
        hub.home.set_view(con, USER, "cards")
        con.execute("INSERT INTO app_data(email, app, key, value, updated) VALUES(?,?,?,?,?)",
                    (USER, "ovn", "hub/summary", json.dumps({"text": "SECRET STORED"}), 100))
    return hub


def test_a_locked_app_shows_no_recipe_line(cards, user_client):
    assert "SECRET LINE" in user_client.get("/").text
    lock(USER, "mat")
    assert "SECRET LINE" not in user_client.get("/").text


def test_a_locked_app_shows_no_stored_line(cards, user_client):
    assert "SECRET STORED" in user_client.get("/").text
    lock(USER, "ovn")
    assert "SECRET STORED" not in user_client.get("/").text


def test_the_line_stays_hidden_while_unlocked(cards, user_client):
    lock(USER, "mat")
    lock(USER, "ovn")
    assert unlock(user_client, "mat").status_code in (200, 303)
    assert "SECRET" not in user_client.get("/").text


def test_the_recipe_is_not_run(cards, user_client, monkeypatch):
    calls = []
    real = cards.card_result
    monkeypatch.setattr(cards, "card_result", lambda user, slug, *a, **kw: calls.append(slug) or real(user, slug, *a, **kw))
    lock(USER, "mat")
    user_client.get("/")
    assert "mat" not in calls


def test_the_card_shows_a_small_lock(cards, user_client):
    lock(USER, "mat")
    html = user_client.get("/").text
    assert html.count('class="summary locked"') == 1
    assert 'aria-label="Krever kode"' in _item(html, "mat")
    assert "summary locked" not in _item(html, "ovn")
    with cards.db() as con:
        cards.home.set_view(con, USER, "icons")
    assert "summary locked" not in user_client.get("/").text


def test_title_icon_and_description_stay(cards, user_client):
    lock(USER, "mat")
    item = _item(user_client.get("/").text, "mat")
    assert "<h2>mat</h2>" in item and "about mat" in item and 'class="icon' in item


def test_another_user_still_sees_the_line(cards, user_client, friend_client):
    with cards.db() as con:
        cards.home.set_view(con, "venn@test.no", "cards")
        cards.home.set_added(con, "venn@test.no", "mat", True)
    lock(USER, "mat")
    assert "SECRET LINE" in friend_client.get("/").text
    assert "SECRET LINE" not in user_client.get("/").text


def test_the_unlocked_user_home_is_unchanged(cards, user_client):
    html = user_client.get("/").text
    assert "summary locked" not in html and "SECRET LINE" in html and "SECRET STORED" in html
