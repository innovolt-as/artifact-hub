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
