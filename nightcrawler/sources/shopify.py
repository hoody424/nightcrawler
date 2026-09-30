"""Any Shopify store via its public /products.json feed.

Many small shops (including second-hand / refurbished resellers) run on
Shopify. The feed has no search, so products are matched locally.
"""

from __future__ import annotations

from collections.abc import Iterator

from bs4 import BeautifulSoup

from ..models import Condition, ListingType, Product, Search, parse_condition
from .base import Source, register


@register("shopify")
class ShopifySource(Source):
    label = "Shopify store"
    description = ("Any shop running on Shopify, read via its public /products.json feed. "
                   "Great for refurbished / second-hand resellers.")
    fields = [
        {"name": "store_url", "label": "Store URL", "type": "text", "required": True,
         "help": "e.g. https://shop.example.com"},
        {"name": "default_condition", "label": "Default condition", "type": "select", "default": "new",
         "choices": ["new", "used", "refurbished", "unknown"],
         "help": "Used when title and tags don't reveal the condition."},
        {"name": "currency", "label": "Currency", "type": "text", "default": "EUR"},
        {"name": "country", "label": "Shop country (ISO code)", "type": "text"},
        {"name": "shipping_cost", "label": "Shipping cost", "type": "number",
         "help": "Flat shipping fee, 0 for free shipping, empty if unknown."},
        {"name": "vendor_is_brand", "label": "'Vendor' field is the brand", "type": "bool", "default": True},
        {"name": "max_pages", "label": "Max pages (250 products each)", "type": "number", "default": 4},
    ]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store_url = self.options["store_url"].rstrip("/")
        self.currency = self.options.get("currency", "EUR")
        self.default_condition = Condition(self.options.get("default_condition", "new"))
        self.max_pages = int(self.options.get("max_pages", 5))

    def _all_products(self) -> Iterator[dict]:
        for page in range(1, self.max_pages + 1):
            resp = self.http.get(f"{self.store_url}/products.json", params={"limit": 250, "page": page})
            products = resp.json().get("products", [])
            if not products:
                return
            yield from products

    def to_product(self, raw: dict) -> Product | None:
        variants = [v for v in raw.get("variants", []) if v.get("available", True)]
        if not variants:
            return None
        cheapest = min(variants, key=lambda v: float(v.get("price") or 0))
        tags = raw.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        hint = " ".join([raw.get("title", ""), cheapest.get("title", ""), *tags])
        condition = parse_condition(hint)
        images = raw.get("images") or []
        body = raw.get("body_html") or ""
        attributes = {"brand": raw.get("vendor"), "category": raw.get("product_type")}
        return Product(
            source=self.name,
            external_id=str(raw["id"]),
            title=raw.get("title", ""),
            url=f"{self.store_url}/products/{raw.get('handle', raw['id'])}",
            price=float(cheapest["price"]) if cheapest.get("price") else None,
            currency=self.currency,
            condition=self.default_condition if condition is Condition.UNKNOWN else condition,
            listing_type=ListingType.FIXED,
            country=self.options.get("country"),
            seller=self.options.get("seller_name", self.name),
            shipping=self.options.get("shipping_cost"),
            image_url=images[0].get("src") if images else None,
            description=BeautifulSoup(body, "lxml").get_text(" ", strip=True)[:500] if body else None,
            # Many shops put their own name in "vendor"; only trust it when told to.
            attributes={k: v for k, v in attributes.items()
                        if v and (k != "brand" or self.options.get("vendor_is_brand", True))},
        )

    def search(self, search: Search) -> Iterator[Product]:
        terms = search.query.lower().split()
        found = 0
        for raw in self._all_products():
            haystack = " ".join([raw.get("title", ""), raw.get("product_type", ""),
                                 raw.get("vendor", ""), str(raw.get("tags", ""))]).lower()
            if not all(t in haystack for t in terms):
                continue
            product = self.to_product(raw)
            if product:
                yield product
                found += 1
                if found >= search.max_results:
                    return
