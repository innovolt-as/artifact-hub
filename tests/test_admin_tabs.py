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


def test_no_reload_on_the_apps_tab(client):
    assert "location.reload" not in client.get("/static/admin-apps.js").text


def test_the_list_refreshes_on_the_way_back_from_the_page_cache(client):
    assert "addEventListener('pageshow', e => { if (e.persisted) refresh(); });" in client.get("/static/admin-apps.js").text


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
    assert "r.redirected" in client.get("/static/admin.js").text
    assert '"loggedOut": "Ikke innlogget"' in admin_client.get("/admin").text


def test_upload_link_and_invite_redirect_an_ended_session(client):
    # the premise of the three tests below: these end on the login page with a 200, not on an error status
    upload = client.post("/api/upload", files={"file": ("a.html", b"x")})
    link = client.post("/api/link", data={"title": "a", "url": "https://a.no"})
    invite = client.post("/api/people/invite", json={"email": "a@a.no"})
    assert [r.status_code for r in (upload, link, invite)] == [302, 302, 302]


def test_upload_and_link_notice_an_ended_session_or_a_lost_network(client):
    js = client.get("/static/admin-upload.js").text
    assert "await reach(fetch('/api/upload'" in js and "await reach(fetch('/api/link'" in js
    assert "await fetch(" not in js


def test_the_uploading_line_goes_whatever_the_answer(client):
    # nothing reloads this tab, so a line left behind reads as still running, under a ✓ or an ✗
    js = client.get("/static/admin-upload.js").text
    assert js.count("busy.remove();") == 1
    assert js.index("await reach(fetch('/api/upload'") < js.index("busy.remove();") < js.index("if (r.ok) {")


def test_every_post_on_the_people_tab_notices_an_ended_session(client):
    js = client.get("/static/admin-people.js").text
    assert js.count("await reach(postJson(") == 3 and "await postJson(" not in js


def test_the_apps_tab_uses_the_shared_reach(client):
    js = client.get("/static/admin-apps.js").text
    assert "const reach" not in js and "reach } = window.Admin" in js


@pytest.mark.parametrize("path", ["/admin/upload", "/admin/people"])
def test_the_error_texts_reach_the_upload_and_people_tabs(path, admin_client):
    html = admin_client.get(path).text
    assert '"loggedOut":' in html and '"netError":' in html


def test_the_upload_log_links_to_the_app(client):
    js = client.get("/static/admin-upload.js").text
    assert "document.createElement('a')" in js and "innerHTML" not in js
    # hub.css takes the underline off every link, and in the log nothing else says it is one
    assert ".log a { text-decoration: underline; }" in client.get("/static/hub.css").text


def test_clicks_just_after_open_are_ignored_inside_the_sheet(client):
    # the second click of a double click on a row lands in the sheet, and on a switch it would change a setting
    js = client.get("/static/admin-apps.js").text
    assert "stopPropagation" in js and "e.preventDefault(); e.stopPropagation();" in js


def test_sub_views_live_in_the_sheet(admin_client):
    html = admin_client.get("/admin").text
    sheet = html[html.index('id="appSheet"'):html.index("</dialog>", html.index('id="appSheet"'))]
    for form in ('id="editForm"', 'id="accessForm"', 'data-view="share"'):
        assert form in sheet
    assert html.count("<dialog") == 1


@pytest.mark.parametrize("view", ["edit", "access", "share"])
def test_each_sub_view_starts_hidden_and_has_a_way_back(view, admin_client):
    html = admin_client.get("/admin").text
    section = html[html.index(f'<section class="editor view" data-view="{view}" hidden>'):]
    section = section[:section.index("</section>")]
    assert '<button type="button" class="view-back" aria-label="Tilbake">‹</button>' in section
    assert 'class="small view-cancel"' in section
    assert '<h1 tabindex="-1">' in section  # the view takes the focus on its heading, as the dialogs did
    assert 'class="err small" role="alert"' in section  # a failed save stays in the view, with the error


def test_the_old_dialogs_are_gone(admin_client, client):
    html = admin_client.get("/admin").text
    for gone in ('id="accessDlg"', 'id="editor"', 'id="shareDlg"'):
        assert gone not in html
    js = client.get("/static/admin-apps.js").text
    assert js.count("showModal") == 1  # the sheet is the only dialog on the page


def test_sheet_styles_the_forms_without_a_box_of_their_own(client):
    css = client.get("/static/hub.css").text
    assert ".sheet .editor { border: 0; width: auto; padding: 8px 18px 18px; background: none; }" in css


def _show(client):
    js = client.get("/static/admin-apps.js").text
    return js[js.index("function show("):js.index("function open(")]


def test_every_way_out_of_a_view_puts_the_data_switch_back(client):
    # the view has no close event of its own: ‹, Cancel, a save and the sheet closing all pass through show()
    assert "$('asData').checked = rowOf(current)?.dataset.shared === '1'" in _show(client)
    js = client.get("/static/admin-apps.js").text
    assert "sheet.addEventListener('close', () => {\n    show('main');" in js


def test_the_double_click_guard_covers_every_change_of_view(client):
    # a double click on Cancel lands on the main view, where the same spot can be a switch
    assert "shownAt = performance.now();" in _show(client)


def test_a_rename_moves_the_sheet_only_if_it_still_shows_that_app(client):
    # the sheet can be closed and opened on another app while the save is on its way
    assert "if (renamed && current === slug) current = renamed;" in client.get("/static/admin-apps.js").text


def test_a_rename_retags_the_row_before_the_refresh_that_may_fail(client):
    # the sheet finds its app through the row, and only a refresh that works brings a row with the new address
    js = client.get("/static/admin-apps.js").text
    retag = js.index("li.dataset.slug = renamed")
    assert retag < js.index("if (renamed && current === slug)") < js.index("await saved();  // refresh() counts")


def test_edit_returns_new_slug(hub, admin_client):
    hub.save_page("gammel", "<!doctype html><title>x</title>", create=True, private=False)
    r = admin_client.post("/api/edit", data={"slug": "gammel", "new_slug": "ny", "title": "Ny"})
    assert r.status_code == 200 and r.json()["slug"] == "ny"
