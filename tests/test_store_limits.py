"""One user cannot fill the disk through an app's storage."""


def test_documents_have_a_total_per_user_and_app(hub, user_client, make_page, monkeypatch):
    make_page("p")
    monkeypatch.setattr(hub, "MAX_STORE_BYTES", 3000)
    assert user_client.put("/api/store/p/d?path=a/1", json={"x": "y" * 2000}).status_code == 200
    r = user_client.put("/api/store/p/d?path=a/2", json={"x": "y" * 2000})
    assert r.status_code == 413 and r.json()["detail"] == "Lagringsplassen for denne appen er full"
    # replacing a document counts its new size, not both
    assert user_client.put("/api/store/p/d?path=a/1", json={"x": "y" * 2500}).status_code == 200
    # another app has room of its own
    make_page("q")
    assert user_client.put("/api/store/q/d?path=a/1", json={"x": "y" * 2000}).status_code == 200


def test_documents_have_a_count_limit(hub, user_client, make_page, monkeypatch):
    make_page("p")
    monkeypatch.setattr(hub, "MAX_STORE_DOCS", 2)
    for i in (1, 2):
        assert user_client.put(f"/api/store/p/d?path=a/{i}", json={}).status_code == 200
    assert user_client.put("/api/store/p/d?path=a/3", json={}).status_code == 413
    assert user_client.put("/api/store/p/d?path=a/2", json={"x": 1}).status_code == 200


def test_data_api_only_for_apps_you_can_see(hub, user_client, admin_client, make_page):
    make_page("mine", "admin")
    assert user_client.put("/api/data/finnes-ikke/k", json={"value": 1}).status_code == 404
    assert user_client.put("/api/data/mine/k", json={"value": 1}).status_code == 404
    assert admin_client.put("/api/data/mine/k", json={"value": 1}).status_code == 200
