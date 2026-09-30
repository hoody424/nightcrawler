from pathlib import Path

from nightcrawler.config import HttpSettings
from nightcrawler.http import HttpClient
from nightcrawler.models import Condition, ListingType, Search
from nightcrawler.sources import build_source
from nightcrawler.sources.ebay import EbaySource
from nightcrawler.sources.html import HtmlSource
from nightcrawler.sources.shopify import ShopifySource

HTML = (Path(__file__).parent / "fixtures" / "shop.html").read_text()
HTTP = HttpClient(HttpSettings(delay_seconds=0))


def html_source(**extra) -> HtmlSource:
    options = {
        "search_url": "https://shop.example/search?q={query}",
        "selectors": {"item": "li.result", "title": "a.title", "price": ".price", "shipping": ".ship",
                      "image": "img", "condition": ".cond", "location": ".loc"},
        "default_condition": "used", **extra,
    }
    return build_source("shop", "html", options, HTTP)


def test_html_parse_page():
    items = list(html_source().parse_page(HTML, "https://shop.example/search?q=thinkpad"))
    assert [p.external_id for p in items] == ["a1", "a2", "a3"]
    first, second, third = items
    assert first.url == "https://shop.example/p/a1"
    assert first.price == 389.0 and first.shipping == 5.99
    assert first.listing_type is ListingType.OFFER  # "VB"
    assert first.condition is Condition.USED
    assert first.image_url == "https://shop.example/img/a1.jpg"
    assert first.location == "10115 Berlin"
    assert second.price == 1299.0 and second.shipping == 0.0 and second.condition is Condition.NEW
    assert third.url == "https://other.example/p/a3" and third.shipping is None
    assert third.title == "ThinkPad Netzteil 65W original"  # truncated text replaced by title attribute


def test_html_local_filter_when_no_query_placeholder(monkeypatch):
    src = html_source(search_url="https://shop.example/laptops?page={page}", max_pages=1)

    class Resp:
        text = HTML

    monkeypatch.setattr(src.http, "get", lambda url, **kw: Resp())
    titles = [p.title for p in src.search(Search(name="t", query="carbon"))]
    assert titles == ["ThinkPad X1 Carbon Gen 9 neu OVP"]


def test_ebay_parse_item_and_filter():
    src = EbaySource("ebay", {"client_id": "x", "client_secret": "y", "item_location_country": "DE"}, HTTP)
    item = {
        "itemId": "v1|123|0", "title": "Nintendo Switch OLED", "itemWebUrl": "https://ebay.de/itm/123",
        "price": {"value": "249.00", "currency": "EUR"}, "conditionId": "3000",
        "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
        "shippingOptions": [{"shippingCost": {"value": "4.99"}}, {"shippingCost": {"value": "6.99"}}],
        "itemLocation": {"postalCode": "80331", "country": "DE"},
        "seller": {"username": "gamer42", "feedbackPercentage": "99.8"},
        "categories": [{"categoryName": "Konsolen"}],
    }
    p = src.parse_item(item)
    assert (p.price, p.shipping, p.country, p.seller, p.seller_rating) == (249.0, 4.99, "DE", "gamer42", 99.8)
    assert p.condition is Condition.USED and p.listing_type is ListingType.OFFER
    flt = src.build_filter(Search(name="s", query="q", conditions=[Condition.USED], min_price=100, max_price=300))
    assert "conditionIds:{2750|3000|4000|5000|6000|7000}" in flt
    assert "itemLocationCountry:DE" in flt and "price:[100..300]" in flt


def test_shopify_to_product():
    src = ShopifySource("refurb", {"store_url": "https://refurb.example/", "default_condition": "refurbished",
                                   "shipping_cost": 0}, HTTP)
    raw = {"id": 7, "title": "iPad Air 64GB", "handle": "ipad-air", "vendor": "Apple", "product_type": "Tablets",
           "tags": "sale", "body_html": "<p>Top <b>Zustand</b></p>",
           "variants": [{"price": "299.00", "available": True, "title": "Grade A"},
                        {"price": "249.00", "available": True, "title": "Grade B"}],
           "images": [{"src": "https://cdn.example/1.jpg"}]}
    p = src.to_product(raw)
    assert p.price == 249.0 and p.condition is Condition.REFURBISHED and p.shipping == 0
    assert p.url == "https://refurb.example/products/ipad-air"
    assert p.attributes == {"brand": "Apple", "category": "Tablets"}
    assert p.description == "Top Zustand"
