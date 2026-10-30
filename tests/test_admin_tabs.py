import pytest


@pytest.mark.parametrize("path", ["/admin", "/admin/upload", "/admin/people", "/admin/stats"])
def test_admin_tabs_are_admin_only(path, admin_client, user_client, client):
    assert admin_client.get(path).status_code == 200
    assert user_client.get(path).status_code == 403
    r = client.get(path)
    assert r.status_code == 302 and "/login" in r.headers["location"]


@pytest.mark.parametrize("path, current", [("/admin", "/admin"), ("/admin/upload", "/admin/upload"),
                                           ("/admin/people", "/admin/people"), ("/admin/stats", "/admin/stats")])
def test_every_tab_is_marked_and_admin_stays_active(path, current, admin_client):
    html = admin_client.get(path).text
    assert f'<a href="{current}" aria-current="page"' in html
    assert html.count('aria-current="page"') == 1
    assert 'href="/admin" class="active"' in html


def test_tabs_in_order(admin_client):
    html = admin_client.get("/admin").text
    order = [html.index(f'href="{p}"', html.index('class="tabs"')) for p in ("/admin/upload", "/admin/people", "/admin/stats")]
    assert order == sorted(order)


def test_upload_lives_on_its_tab(admin_client):
    assert 'id="drop"' in admin_client.get("/admin/upload").text
    assert 'id="linkForm"' in admin_client.get("/admin/upload").text
    assert 'id="drop"' not in admin_client.get("/admin").text


def test_people_lives_on_its_tab(admin_client):
    assert 'id="inviteForm"' in admin_client.get("/admin/people").text
    assert 'id="inviteForm"' not in admin_client.get("/admin").text


def test_upload_page_does_not_reload(client):
    assert "location.reload" not in client.get("/static/admin-upload.js").text


def test_apps_page_does_not_reload(client):
    assert "location.reload" not in client.get("/static/admin-apps.js").text


def _page(hub, slug, **meta):
    hub.save_page(slug, f"<!doctype html><title>{slug}</title>", create=True, private=False)
    p = hub._meta_path(slug)
    hub._write_meta(p, {**hub._read_meta(p), **meta})


def _row(html, marker):
    row = html[html.index(marker):]
    return row[:row.index("</li>")]


def test_rows_have_no_buttons_but_carry_the_state(hub, admin_client):
    _page(hub, "radar", data="shared", banner=False)
    html = admin_client.get("/admin").text
    row = _row(html, 'data-slug="radar"')
    assert 'data-shared="1"' in row and 'data-banner="0"' in row and 'class="arow"' in row
    assert "felles data" in row and "uten banner" in row
    for gone in ('class="small edit"', 'class="small banner"', 'class="small datamode"', 'class="small danger del"'):
        assert gone not in html


def test_plain_row_says_only_the_access(hub, admin_client):
    _page(hub, "enkel")
    row = _row(admin_client.get("/admin").text, 'data-slug="enkel"')
    assert 'data-shared="0"' in row and 'data-banner="1"' in row
    assert "<small>🌍 Alle</small>" in row


def test_link_rows_say_link(hub, admin_client):
    admin_client.post("/api/link", data={"title": "Lenka", "url": "https://x.test/"})
    row = _row(admin_client.get("/admin").text, 'data-kind="link"')
    assert "<small>🌍 Alle · lenke</small>" in row and 'data-kindlabel="lenke"' in row
    assert 'data-url="https://x.test/"' in row


def test_warning_stays_on_the_row(hub, make_page, admin_client):
    from app import shared
    make_page("finn", "all")
    make_page("mine", "admin")
    with hub.db() as con:
        shared.record_write(con, "finn", "admin@test.no")
        shared.record_write(con, "mine", "admin@test.no")
    html = admin_client.get("/admin").text
    finn = _row(html, 'data-slug="finn"')
    assert "Claude fyller denne appen med dine personlige data." in finn and 'data-warned="1"' in finn
    mine = _row(html, 'data-slug="mine"')
    assert 'data-claude="1"' in mine and 'data-warned="0"' in mine


def test_empty_list_points_to_upload(admin_client):
    assert 'href="/admin/upload"' in admin_client.get("/admin").text.split('id="appList"')[1]


def test_sheet_markup(admin_client):
    html = admin_client.get("/admin").text
    for id_ in ("appSheet", "asEdit", "asAccess", "asData", "asBanner", "asDelete", "asError", "asWarn", "appSearch"):
        assert f'id="{id_}"' in html
    assert html.index('id="asBanner"') < html.index('id="asDelete"')
    assert html.count('role="switch"') == 2


def test_picker_rules_stay_out_of_other_sheets(client):
    css = client.get("/static/hub.css").text
    assert "#picker input[type=checkbox]" in css
    assert ".sheet input[type=checkbox]" not in css


def test_a_redirect_counts_as_logged_out(client, admin_client):
    # fetch follows the hub's 302 to /login and sees a 200, so the script has to look for the redirect itself
    r = client.post("/api/toggle-banner", data={"slug": "a"})
    assert r.status_code == 302 and "/login" in r.headers["location"]
    assert "r.redirected" in client.get("/static/admin-apps.js").text
    assert '"loggedOut": "Ikke innlogget"' in admin_client.get("/admin").text


def test_clicks_just_after_open_are_ignored_inside_the_sheet(client):
    # the second click of a double click on a row lands in the sheet, and on a switch it would change a setting
    js = client.get("/static/admin-apps.js").text
    assert "stopPropagation" in js and "e.preventDefault(); e.stopPropagation();" in js
