from conftest import make_product

from nightcrawler.ai import AI, Backend
from nightcrawler.crawler import Crawler, matches
from nightcrawler.filters import ProductFilter, search_products
from nightcrawler.models import Condition, Search


class FakeBackend(Backend):
    name = "fake"

    def __init__(self):
        self.calls = []

    def structured(self, system, prompt, schema, effort):
        self.calls.append(prompt)
        # Reject anything that looks like an accessory, extract a model name.
        import json
        listings = json.loads(prompt.split("Listings:\n", 1)[1])
        return {"items": [{"id": item["id"], "relevant": "netzteil" not in item["title"].lower(),
                           "reason": "accessory" if "netzteil" in item["title"].lower() else "laptop",
                           "attributes": [{"name": "model", "value": "ThinkPad T14"}]} for item in listings]}


def test_matches():
    s = Search(name="s", query="q", conditions=[Condition.USED], min_price=10, max_price=100,
               include_keywords=["thinkpad"], exclude_keywords=["defekt"])
    ok = make_product("1", "ThinkPad T14", 50)
    assert matches(ok, s)
    assert not matches(make_product("2", "ThinkPad defekt", 50), s)
    assert not matches(make_product("3", "ThinkPad", 500), s)
    assert not matches(make_product("4", "ThinkPad", None), s)
    assert not matches(make_product("5", "ThinkPad", 50, condition=Condition.NEW), s)
    assert not matches(make_product("6", "Dell", 50), s)


def test_run_search_end_to_end(db):
    products = [make_product("1", "ThinkPad T14 16GB", 300), make_product("2", "ThinkPad Netzteil", 20),
                make_product("3", "ThinkPad X1", 5000)]
    db.save_source({"name": "fake", "type": "fake", "options": {"products": []}})
    row = db.save_search({"name": "tp", "query": "thinkpad", "max_price": 1000, "ai_filter": "only laptops"})
    search = db.search_obj(row)
    backend = FakeBackend()
    crawler = Crawler(db, ai=AI(backend, max_calls_per_hour=0))
    # Options are JSON in the DB, so inject products by patching the built source.
    import nightcrawler.crawler as crawler_mod
    real_build = crawler_mod.build_source
    crawler_mod.build_source = lambda name, kind, options, http: real_build(name, kind, {"products": products}, http)
    try:
        result = crawler.run_search(search, "test")
    finally:
        crawler_mod.build_source = real_build

    assert result.status == "ok", result.errors
    assert (result.fetched, result.matched, len(result.new)) == (3, 2, 2)
    assert len(backend.calls) == 1
    visible = search_products(db, ProductFilter())
    assert [p["external_id"] for p in visible["items"]] == ["1"]  # accessory rejected by AI
    assert search_products(db, ProductFilter(include_rejected=True))["total"] == 2
    detail = db.get_product("fake:1")
    assert detail["attributes"]["model"] == "ThinkPad T14"
    run = db.list_runs()[0]
    assert run["status"] == "ok" and run["new"] == 2


def test_failing_source_marks_run_error(db):
    db.save_source({"name": "broken", "type": "fake", "options": {"fail": True}})
    search = db.search_obj(db.save_search({"name": "x", "query": "x"}))
    result = Crawler(db).run_search(search)
    assert result.status == "error" and "boom" in result.errors[0]


def test_ai_filter_without_backend_reports(db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    db.update_settings({"ai_backend": "off"})
    import nightcrawler.crawler as crawler_mod
    real_build = crawler_mod.build_source
    monkeypatch.setattr(crawler_mod, "build_source",
                        lambda n, k, o, h: real_build(n, k, {"products": [make_product("1", "thing", 5)]}, h))
    db.save_source({"name": "fake", "type": "fake", "options": {}})
    search = db.search_obj(db.save_search({"name": "x", "query": "x", "ai_filter": "only things"}))
    result = Crawler(db).run_search(search)
    assert result.status == "partial" and "no Claude connection" in result.errors[0]
