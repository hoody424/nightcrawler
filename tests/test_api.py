import pytest
from conftest import make_product
from fastapi.testclient import TestClient

from nightcrawler.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("NIGHTCRAWLER_USERNAME", raising=False)
    app = create_app(str(tmp_path / "api.db"), run_scheduler=False)
    with TestClient(app) as c:
        yield c


def test_meta_and_ui(client):
    meta = client.get("/api/meta").json()
    assert {t["type"] for t in meta["source_types"]} >= {"ebay", "html", "shopify"}
    assert any(a["name"] == "storage_gb" for a in meta["attributes"])
    assert "nightcrawler" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_crud_and_search(client):
    r = client.post("/api/sources", json={"name": "shop", "type": "html", "options": {
        "search_url": "https://shop.example/?q={query}", "selectors": {"item": "li", "title": "a"}}})
    assert r.status_code == 201
    r = client.post("/api/searches", json={"name": "tp", "query": "thinkpad", "conditions": ["used"], "max_price": 500})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post("/api/searches", json={"name": "tp", "query": "x"}).status_code == 409

    db = client.app.state.db
    search = db.search_obj(db.get_search(sid))
    db.upsert_products(search, [make_product("1", "ThinkPad T14 16GB RAM", 300)])
    res = client.post("/api/products/search", json={"q": "t14"}).json()
    assert res["total"] == 1 and res["facets"]["attributes"]["ram_gb"]["values"][0]["value"] == "16"
    key = res["items"][0]["key"]
    assert client.patch(f"/api/products/{key}", json={"favorite": True}).json()["favorite"] is True
    assert client.get(f"/api/products/{key}").json()["matches"][0]["search_name"] == "tp"
    csv = client.get("/api/export?format=csv").text
    assert "ThinkPad T14 16GB RAM" in csv and "ram_gb" in csv
    assert client.delete(f"/api/searches/{sid}").status_code == 204


def test_settings_secret_is_masked(client):
    s = client.put("/api/settings", json={"ai_oauth_token": "sk-ant-oat-secret", "retention_days": 30}).json()
    assert s["ai_oauth_token"] == "••••••••" and s["retention_days"] == 30
    # Sending the mask back must not overwrite the stored secret.
    client.put("/api/settings", json={"ai_oauth_token": "••••••••"})
    assert client.app.state.db.get_settings()["ai_oauth_token"] == "sk-ant-oat-secret"
    assert client.put("/api/settings", json={"nope": 1}).status_code == 422


def test_ai_endpoints_need_connection(client, monkeypatch):
    client.put("/api/settings", json={"ai_backend": "off"})
    assert client.post("/api/ai/parse-filter", json={"text": "x"}).status_code == 409


def test_basic_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTCRAWLER_USERNAME", "admin")
    monkeypatch.setenv("NIGHTCRAWLER_PASSWORD", "pw")
    with TestClient(create_app(str(tmp_path / "a.db"), run_scheduler=False)) as c:
        assert c.get("/api/meta").status_code == 401
        assert c.get("/api/meta", auth=("admin", "pw")).status_code == 200
        assert c.get("/health").status_code == 200
