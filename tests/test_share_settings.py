"""The share button on owner pages, and the "Shared links" card on the settings page."""
import pytest

from tests.test_share_links import U, share, token_of
from tests.test_shared_data import make_shared


@pytest.fixture
def pub(hub, make_page):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True)


def _banner(html: str) -> str:
    return html.split("<hub-banner>")[1].split("</hub-banner>")[0]


# ---------------------------------------------------------------- the button on app pages
def test_banner_has_share_button_only_for_public_apps(hub, pub, make_page, user_client):
    r = user_client.get("/a/radar/")
    assert 'class="share"' in _banner(r.text) and "<dialog" in _banner(r.text)
    tag = next(s for s in r.text.split("<script") if "/static/share.js" in s)
    assert 'data-slug="radar"' in tag and "defer" in tag and 'data-strings="' in tag and "&quot;create&quot;" in tag
    make_page("plain")
    plain = user_client.get("/a/plain/").text
    assert 'class="share"' not in plain and "share.js" not in plain and "<dialog" not in plain


def test_no_share_button_when_the_banner_is_off(hub, pub, user_client, admin_client):
    meta = hub._read_meta(hub._meta_path("radar"))
    meta["banner"] = False
    hub._write_meta(hub._meta_path("radar"), meta)
    text = user_client.get("/a/radar/").text
    assert 'class="share"' not in text and "share.js" not in text


def test_no_share_button_in_guest_mode(hub, pub, user_client, client):
    token = token_of(share(user_client))
    text = client.get(f"/p/{token}/").text
    assert 'class="share"' not in text and "share.js" not in text and "<dialog" not in text


# ---------------------------------------------------------------- the settings card
def test_settings_lists_my_links(hub, pub, user_client):
    r = share(user_client, title="Jul <b>")
    html = user_client.get("/settings").text
    assert 'id="shareCard"' in html
    assert r.json()["link"]["url"] in html and "Jul &lt;b&gt;" in html and "Jul <b>" not in html
    assert 'data-slug="radar"' in html and 'data-name="jul"' in html and "radar" in html
    assert "0 svar fra gjester" in html


def test_settings_row_counts_guest_replies(hub, pub, user_client):
    from tests.test_public_settings import add_guest_docs
    share(user_client, title="Jul")
    add_guest_docs(hub, "radar", U, "jul", 1)
    assert "1 svar fra gjester" in user_client.get("/settings").text


def test_settings_card_hidden_without_links_or_public_apps(hub, make_page, user_client):
    make_page("plain")
    assert "shareCard" not in user_client.get("/settings").text
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True)
    assert "shareCard" not in user_client.get("/settings").text  # a public app without a link is not listed


def test_settings_card_gone_after_the_link_is_off(hub, pub, user_client):
    share(user_client)
    share(user_client, action="off")
    assert "shareCard" not in user_client.get("/settings").text


def test_settings_card_in_english(hub, pub, user_client, english):
    share(user_client, title="Jul")
    html = user_client.get("/settings").text
    assert "Shared links" in html and "0 replies from guests" in html and "Delte" not in html
    assert "/static/settings-share.js" in html
