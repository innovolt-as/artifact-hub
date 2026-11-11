"""Admin page: the app settings sheet in four groups, with the public sharing and agent zone rows."""
import json
import re

from tests.test_public_settings import add_guest_docs
from tests.test_shared_data import make_shared

GROUPS = ("asgAccess", "asgData", "asgPublic", "asgDisplay")


def _sheet(client):
    html = client.get("/admin").text
    return html[html.index('<dialog id="appSheet"'):html.index('data-view="edit"')]


def _group(sheet, gid):
    """The markup of one group: from its section to the next one (or the end of the main view)."""
    start = sheet.index(f'id="{gid}"')
    nxt = [sheet.index(f'id="{g}"') for g in GROUPS if sheet.index(f'id="{g}"') > start]
    return sheet[start:min(nxt) if nxt else len(sheet)]


def test_admin_sheet_has_four_groups(admin_client, make_page):
    make_page("p")
    sheet = _sheet(admin_client)
    places = [sheet.index(f'id="{g}"') for g in GROUPS]
    assert places == sorted(places)
    headings = re.findall(r'<h2 class="as-heading" id="asg\w+">([^<]+)</h2>', sheet)
    assert headings == ["Hvem kan åpne", "Data", "Offentlig deling", "Visning"]
    wanted = {"asgAccess": ["asAccess"], "asgData": ["asData", "asAppend", "asAppendLabel", "asAgent"],
              "asgPublic": ["asPublic", "asPublicRead", "asGuestsHidden", "asLinks"],
              "asgDisplay": ["asEdit", "asBanner", "asOffline"]}
    for gid, ids in wanted.items():
        for i in ids:
            assert f'id="{i}"' in _group(sheet, gid), (gid, i)
    html = admin_client.get("/admin").text
    for view in ("append", "public_read", "edit", "access"):
        assert f'data-view="{view}"' in html
    assert 'id="appendForm"' in html and 'id="publicReadForm"' in html


def test_public_rows_need_shared_data(hub, make_page, admin_client):
    make_shared(hub, make_page, "radar")
    make_page("plain")
    html = admin_client.get("/admin").text
    row = {s: re.search(rf'<li data-slug="{s}".*?>', html, re.S).group(0) for s in ("radar", "plain")}
    assert 'data-shared="1"' in row["radar"] and 'data-shared="0"' in row["plain"]
    for attr in ("data-public", "data-public-read", "data-guests-hidden", "data-agent"):
        assert attr in row["radar"]
    js = admin_client.get("/static/admin-apps.js").text
    # The rows that need shared data follow the row's shared flag, as the append row does
    for el in ("asAppend", "asAgentRow", "asPublicGroup"):
        assert re.search(rf"\$\('{el}'\)\.hidden = !?shared|\$\('{el}'\)\.hidden = d\.shared !== '1'", js), el
    hub.set_public("radar", public=True, guests_hidden=True, public_read=["products"], agent=True)
    html = admin_client.get("/admin").text
    row = re.search(r'<li data-slug="radar".*?>', html, re.S).group(0)
    assert 'data-public="1"' in row and 'data-guests-hidden="1"' in row and 'data-agent="1"' in row
    assert 'data-public-read="products"' in row


def test_public_settings_route_is_admin_only(hub, make_page, admin_client, user_client):
    make_shared(hub, make_page, "radar")
    assert user_client.get("/api/public-settings", params={"slug": "radar"}).status_code in (401, 403)
    assert user_client.post("/api/public-settings", json={"slug": "radar", "public": True}).status_code in (401, 403)
    assert admin_client.get("/api/public-settings", params={"slug": "radar"}).status_code == 200


def test_clash_count_reported(hub, make_page, admin_client):
    make_shared(hub, make_page, "radar")
    add_guest_docs(hub, "radar", n=3)
    r = admin_client.get("/api/public-settings", params={"slug": "radar"}).json()
    assert r["clash"] == 3 and r["guest_docs"] == 3


def test_sheet_texts_reach_the_script(admin_client, make_page):
    make_page("p")
    html = admin_client.get("/admin").text
    strings = json.loads(re.search(r'id="__admin_strings">(.*?)</script>', html, re.S).group(1))
    for key in ("confirmClashPublic", "confirmClashAgent", "confirmLinksOffOne", "confirmLinksOffOther",
                "confirmWipeGuests"):
        assert strings[key], key
    assert "{n}" in strings["confirmClashPublic"] and "{n}" in strings["confirmLinksOffOther"]
    assert "{n} aktiv lenke slutter" in strings["confirmLinksOffOne"]
    assert "{n} aktive lenker slutter" in strings["confirmLinksOffOther"]
    # the script picks the singular for one link
    js = admin_client.get("/static/admin-apps.js").text
    assert "p.links === 1 ? T.confirmLinksOffOne : T.confirmLinksOffOther" in js


def test_links_off_text_has_a_singular_in_english(admin_client, make_page, english):
    make_page("p")
    html = admin_client.get("/admin").text
    strings = json.loads(re.search(r'id="__admin_strings">(.*?)</script>', html, re.S).group(1))
    assert strings["confirmLinksOffOne"].startswith("{n} active link stops working. It is not deleted")
    assert strings["confirmLinksOffOther"].startswith("{n} active links stop working. They are not deleted")
