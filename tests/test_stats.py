"""Admin statistics: who used which apps in the last 7 days (home.week_stats, /admin/stats)."""
import time

DAY = 86400
NOW = 1_800_000_000


def _opens(hub, email, slug, times, at):
    """`times` separate opens (11 minutes apart, so none is merged as a reload), the last one at `at`."""
    with hub.db() as con:
        for i in reversed(range(times)):
            hub.home.record_visit(con, email, slug, now=at - i * 660)


def test_week_stats_last_7_days_without_admin(hub):
    _opens(hub, "kari@test.no", "a", 3, NOW)
    _opens(hub, "kari@test.no", "b", 1, NOW - 2 * DAY)
    _opens(hub, "ola@test.no", "a", 1, NOW - DAY)
    _opens(hub, "admin@test.no", "a", 5, NOW)
    _opens(hub, "gammel@test.no", "c", 4, NOW - 8 * DAY)
    with hub.db() as con:
        s = hub.home.week_stats(con, exclude={"admin@test.no"}, now=NOW)
    assert s["opens"] == 5
    assert [u["email"] for u in s["users"]] == ["kari@test.no", "ola@test.no"]
    kari = s["users"][0]
    assert kari["opens"] == 4 and kari["apps"] == [("a", 3), ("b", 1)] and kari["last"] == NOW
    assert [a["slug"] for a in s["apps"]] == ["a", "b"]
    assert s["apps"][0]["opens"] == 4 and s["apps"][0]["users"] == [("kari@test.no", 3), ("ola@test.no", 1)]


def test_week_stats_ties_alphabetical_and_empty(hub):
    with hub.db() as con:
        assert hub.home.week_stats(con, now=NOW) == {"opens": 0, "users": [], "apps": []}
    _opens(hub, "b@test.no", "y", 1, NOW)
    _opens(hub, "a@test.no", "x", 1, NOW)
    with hub.db() as con:
        s = hub.home.week_stats(con, now=NOW)
    assert [u["email"] for u in s["users"]] == ["a@test.no", "b@test.no"] and [a["slug"] for a in s["apps"]] == ["x", "y"]


def _stats_html(client):
    html = client.get("/admin/stats").text
    return html[html.find('id="stats"'):]


def test_admin_stats_page(hub, make_page, admin_client):
    make_page("a", title="Alfa")
    make_page("b", title="<b>Beta</b>")
    make_page("c", title="Ubrukt")
    now = int(time.time())
    _opens(hub, "kari@test.no", "a", 2, now)
    _opens(hub, "ola@test.no", "b", 1, now)
    _opens(hub, "kari@test.no", "slettet-app", 1, now)
    _opens(hub, "admin@test.no", "c", 3, now)
    html = _stats_html(admin_client)
    assert "Aktive brukere" in html and "Åpninger" in html
    assert "Alfa" in html and "&lt;b&gt;Beta&lt;/b&gt;" in html and "<b>Beta</b>" not in html
    assert "kari@test.no" in html and "ola@test.no" in html and "admin@test.no" not in html
    assert "slettet-app" in html  # an app that is gone is still counted, by its address
    idle = html[html.find('id="idle"'):].split("</p>")[0]
    assert "Ubrukt" in idle and "Alfa" not in idle
    assert html.index("Alfa") < html.index("&lt;b&gt;Beta")  # most opened first


def test_admin_stats_admin_only_and_tabs(admin_client, user_client):
    assert user_client.get("/admin/stats").status_code == 403
    assert 'href="/admin/stats"' in admin_client.get("/admin").text
    assert 'href="/admin"' in admin_client.get("/admin/stats").text


def test_admin_stats_empty(admin_client):
    assert "Ingen har brukt" in _stats_html(admin_client)
