"""The admin sheet's collection buttons and the warning for an app not written for sharing (app/main.py)."""
import json

import pytest

from app import main, shared
from tests.test_shared_data import make_shared


def add_shared(hub, slug, collection, doc_id="d1", owner=shared.SHARED):
    with hub.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,?,?,0)",
                    (slug, owner, collection, doc_id, json.dumps({"x": 1})))


def settings(c, slug="radar"):
    return c.get("/api/public-settings", params={"slug": slug}).json()


# ---------------------------------------------------------------- collections
def test_collections_of_an_app_without_shared_data(make_page, admin_client):
    make_page("plain")
    assert settings(admin_client, "plain")["collections"] == []


def test_collections_are_the_sorted_top_level_names(hub, make_page, admin_client):
    make_shared(hub, make_page, "radar")
    for col in ("tips", "products/k1/notes", "products", "queue", "tips/sub"):
        add_shared(hub, "radar", col)
    assert settings(admin_client)["collections"] == ["products", "queue", "tips"]


def test_collections_leave_out_invalid_names_the_data_branch_and_other_branches(hub, make_page, admin_client):
    make_shared(hub, make_page, "radar")
    make_page("other")
    for col in ("ok", "bad name", "data", "data/users/a@t.no/x", "x" * 65, "ünï", "a%b", "under_score"):
        add_shared(hub, "radar", col)
    add_shared(hub, "radar", "mine", owner="a@t.no")  # someone's own branch is not a shared collection
    add_shared(hub, "other", "elsewhere")             # another app
    assert settings(admin_client)["collections"] == ["ok", "under_score"]


def test_collections_compare_by_segment_not_like(hub, make_page, admin_client):
    make_shared(hub, make_page, "radar")
    add_shared(hub, "radar", "a_c")   # "_" must not behave as a wildcard anywhere
    add_shared(hub, "radar", "a_c/x")
    assert settings(admin_client)["collections"] == ["a_c"]


# ---------------------------------------------------------------- uses_share
@pytest.mark.parametrize("src, expected", [
    ('<script>const s = window.claude.use("share");</script>', True),
    ("<script>claude.use('share')</script>", True),
    ('<script>claude.use(  "share"\n )</script>', True),
    ('<script>claude.use( \t\'share\' )</script>', True),
    ('<script>claude.use("db")</script>', False),
    ('<script>claude.use("sharee")</script>', False),
    ("<p>use share</p>", False),
])
def test_uses_share_in_a_single_file(make_page, src, expected):
    make_page("p")
    (main.ARTIFACTS_DIR / "p.html").write_text(src, "utf-8")
    assert main.uses_share("p") is expected


def _folder(slug, files):
    root = main.ARTIFACTS_DIR / slug
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, "utf-8")
    return root


USE = 'claude.use("share")'


def test_uses_share_in_a_folder_app():
    _folder("f1", {"index.html": "<body></body>", "app.js": USE})
    _folder("f2", {"index.html": "<body></body>", "js/app.js": USE})
    _folder("f3", {"index.html": "<body></body>", "js/deep/app.js": USE})
    _folder("f4", {"index.html": "<body></body>", "part.html": USE})
    _folder("f5", {"index.html": USE})
    _folder("f6", {"index.html": "<body></body>", "notes.txt": USE})
    assert [main.uses_share(s) for s in ("f1", "f2", "f3", "f4", "f5", "f6")] == [True, True, False, True, True, False]


def test_uses_share_does_not_follow_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.js").write_text(USE, "utf-8")
    (outside / "dir").mkdir()
    (outside / "dir" / "y.js").write_text(USE, "utf-8")
    root = _folder("s1", {"index.html": "<body></body>"})
    (root / "app.js").symlink_to(outside / "x.js")
    (root / "sub").symlink_to(outside / "dir")
    (main.ARTIFACTS_DIR / "s2.html").symlink_to(outside / "x.js")
    assert main.uses_share("s1") is False and main.uses_share("s2") is False


def test_uses_share_stops_listing_after_200_entries():
    files = {"index.html": "<body></body>"} | {f"a{i:03}.txt": "" for i in range(200)} | {"z.js": USE}
    _folder("many", files)
    assert main.uses_share("many") is False


def test_uses_share_reads_at_most_two_megabytes():
    big = "x" * (2 * 1024 * 1024 + 10)
    _folder("g1", {"index.html": big, "app.js": USE})   # the match lies past the limit
    _folder("g2", {"index.html": "x" * 1000, "app.js": USE})
    assert main.uses_share("g1") is False and main.uses_share("g2") is True


def test_uses_share_false_for_a_link_card_and_a_missing_app(admin_client):
    (main.ARTIFACTS_DIR / "ext.link.json").write_text(json.dumps({"url": "https://example.com", "title": "E"}), "utf-8")
    assert main.uses_share("ext") is False
    assert main.uses_share("nope") is False
    assert main.uses_share("../etc") is False


def test_settings_report_uses_share(hub, make_page, admin_client):
    make_shared(hub, make_page, "radar")
    assert settings(admin_client)["uses_share"] is False
    (main.ARTIFACTS_DIR / "radar.html").write_text(USE, "utf-8")
    assert settings(admin_client)["uses_share"] is True


# ---------------------------------------------------------------- ready
def test_share_answers_say_whether_the_app_is_ready(hub, make_page, user_client):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True)
    got = user_client.get("/api/share/radar", params={"name": "jul"}).json()
    assert got["ready"] is False
    (main.ARTIFACTS_DIR / "radar.html").write_text(USE, "utf-8")
    assert user_client.get("/api/share/radar", params={"name": "jul"}).json()["ready"] is True
    r = user_client.post("/api/share/radar", json={"name": "jul", "action": "create"}).json()
    assert r["ready"] is True
    items = user_client.get("/api/share").json()["links"]
    assert items[0]["ready"] is True
    (main.ARTIFACTS_DIR / "radar.html").write_text("<body></body>", "utf-8")
    assert user_client.get("/api/share").json()["links"][0]["ready"] is False


# ---------------------------------------------------------------- the sheet: markup, texts and script
def _strings(client):
    import re
    html = client.get("/admin").text
    return json.loads(re.search(r'id="__admin_strings">(.*?)</script>', html, re.S).group(1))


def _view(html, name):
    start = html.index(f'data-view="{name}"')
    return html[start:html.index("</section>", start)]


def test_both_views_have_chips_a_field_an_add_button_and_keep_their_ids(admin_client, make_page):
    make_page("p")
    html = admin_client.get("/admin").text
    for view, p, form in (("append", "ap", "appendForm"), ("public_read", "pr", "publicReadForm")):
        v = _view(html, view)
        for i in (form, f"{p}Names", f"{p}Chips", f"{p}Add", f"{p}None", f"{p}Error"):
            assert f'id="{i}"' in v, (view, i)
        assert 'name="names"' in v
        assert v.index(f'id="{p}Chips"') < v.index(f'id="{p}Names"')  # the buttons come above the field
    sheet = html[html.index('<dialog id="appSheet"'):]
    # the hint sits right under the Public sharing switch, before the Guests can read row
    assert sheet.index('id="asPublic"') < sheet.index('id="asUnready"') < sheet.index('id="asPublicRead"')
    assert 'maxlength="800"' in _view(html, "append") and 'maxlength="800"' in _view(html, "public_read")
    assert html.index("admin-chips.js") < html.index("admin-apps.js")  # the script reads AdminChips when it loads


def test_new_texts_reach_the_script_in_both_languages(admin_client, make_page, english):
    make_page("p")
    strings = _strings(admin_client)
    for key in ("chipBad", "chipInAppend", "chipInPublicRead", "chipOther", "confirmUnreadyPublic"):
        assert strings[key], key
    assert "{name}" in strings["chipBad"] and "{name}" in strings["chipOther"]
    assert "does not seem to use sharing" in strings["confirmUnreadyPublic"]


def test_the_script_asks_about_sharing_first_and_posts_what_it_posted_before():
    from pathlib import Path
    js = (Path(main.__file__).parent / "static" / "admin-apps.js").read_text("utf-8")
    ask = js[js.index("guarded($('asPublic')"):]
    assert ask.index("T.confirmUnreadyPublic") < ask.index("T.confirmClashPublic")
    assert "fd.append('names', append.selected().join(', '))" in js
    assert "setPublic({ public_read: list })" in js
    assert "$('asUnready').hidden = p.uses_share !== false" in js
    assert "aria-pressed" in js and "textContent" in js


def test_chip_style_is_at_least_44px_tall():
    from pathlib import Path
    css = (Path(main.__file__).parent / "static" / "hub.css").read_text("utf-8")
    rule = next(line for line in css.splitlines() if line.startswith(".chip {"))
    assert "min-height: 44px" in rule
    assert '.chip[aria-pressed="true"]' in css


# ---------------------------------------------------------------- the settings page: the warning per link
def test_shared_links_card_warns_for_an_app_not_written_for_sharing(hub, make_page, user_client):
    import re
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True)
    user_client.post("/api/share/radar", json={"name": "jul", "action": "create"})
    row = lambda: re.search(r'<p class="warn small swarn"[^>]*>', user_client.get("/settings").text).group(0)  # noqa: E731
    assert "hidden" not in row()
    (main.ARTIFACTS_DIR / "radar.html").write_text(USE, "utf-8")
    assert "hidden" in row()
