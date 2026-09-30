from conftest import make_product

from nightcrawler.filters import ProductFilter, search_products
from nightcrawler.models import Condition, ListingType


def seed(db, search):
    products = [
        make_product("1", "Lenovo ThinkPad T14 16GB RAM 512GB SSD", 400, shipping=5, seller_rating=99.9, country="DE"),
        make_product("2", "Lenovo ThinkPad T14 8GB RAM 256GB SSD defekt", 150, shipping=0, country="DE",
                     listing_type=ListingType.AUCTION),
        make_product("3", "Apple MacBook Air M1 8GB 256GB OVP", 650, condition=Condition.NEW, shipping=0,
                     seller_rating=98.0, country="AT"),
        make_product("4", "Dell XPS 13 16/512GB i7", 500, condition=Condition.REFURBISHED),
        make_product("5", "HP EliteBook 840 G8 16GB 512GB", 450, shipping=None),
    ]
    db.upsert_products(search, products)
    db.update_deal_scores(search.id)


def run(db, **kw):
    return search_products(db, ProductFilter(**kw))


def test_basic_and_price(db, search):
    seed(db, search)
    assert run(db)["total"] == 5
    assert run(db, price_max=450)["total"] == 3
    assert run(db, price_max=402)["total"] == 2
    assert run(db, price_max=402, include_shipping=True)["total"] == 1  # 400 + 5 shipping > 402
    assert {p["external_id"] for p in run(db, free_shipping=True)["items"]} == {"2", "3"}


def test_disjunctive_facets(db, search):
    seed(db, search)
    res = run(db, conditions=["new"])
    assert res["total"] == 1
    # The condition facet ignores its own selection, so alternatives stay visible with counts.
    counts = {v["value"]: v["count"] for v in res["facets"]["conditions"]}
    assert counts == {"used": 3, "new": 1, "refurbished": 1}
    # Other facets are narrowed by the condition filter.
    brands = {v["value"]: v["count"] for v in res["facets"]["attributes"]["brand"]["values"]}
    assert brands == {"Apple": 1}


def test_attribute_filters(db, search):
    seed(db, search)
    assert {p["external_id"] for p in run(db, attrs={"ram_gb": ["16"]})["items"]} == {"1", "4", "5"}
    assert run(db, attrs={"brand": ["Lenovo", "Apple"]})["total"] == 3  # OR within a facet
    assert run(db, attrs={"brand": ["Lenovo"], "ram_gb": ["16"]})["total"] == 1  # AND across facets
    assert run(db, ranges={"storage_gb": [300, None]})["total"] == 3
    assert "2" not in {p["external_id"] for p in run(db, flags={"defective": "exclude"})["items"]}
    assert [p["external_id"] for p in run(db, flags={"original_box": "only"})["items"]] == ["3"]
    flag = run(db)["facets"]["attributes"]["defective"]
    assert flag == {"only": 1, "exclude": 4}


def test_misc_filters_and_sorting(db, search):
    seed(db, search)
    assert run(db, listing_types=["auction"])["total"] == 1
    assert run(db, countries=["AT"])["total"] == 1
    assert run(db, seller_rating_min=99)["total"] == 1
    prices = [p["price"] for p in run(db, sort="price_asc")["items"]]
    assert prices == sorted(prices)
    deals = run(db, sort="deal")["items"]
    assert deals[0]["deal_pct"] is not None
    hist = run(db)["facets"]["price"]
    assert hist["min"] == 150 and hist["max"] == 650 and sum(b["count"] for b in hist["histogram"]) == 5
    page = run(db, per_page=2, page=3)
    assert page["pages"] == 3 and len(page["items"]) == 1


def test_price_drop_and_gone(db, search):
    seed(db, search)
    db.upsert_products(search, [make_product("1", "Lenovo ThinkPad T14 16GB RAM 512GB SSD", 350)])
    dropped = run(db, price_dropped=True)["items"]
    assert [p["external_id"] for p in dropped] == ["1"] and dropped[0]["drop_pct"] == 12.5
    for _ in range(2):
        db.mark_missed(search.id, "fake", "9999-01-01T00:00:00+00:00")
    assert run(db)["total"] == 0
    assert run(db, status="gone")["total"] == 5


def test_hidden_and_favorites(db, search):
    seed(db, search)
    db.update_product("fake:1", hidden=True)
    db.update_product("fake:2", favorite=True)
    assert run(db)["total"] == 4
    assert run(db, include_hidden=True)["total"] == 5
    assert [p["external_id"] for p in run(db, favorites=True)["items"]] == ["2"]
