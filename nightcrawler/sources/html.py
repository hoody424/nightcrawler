"""Generic HTML source driven entirely by CSS selectors from the config.

Use this for shops without an API. Check the site's terms of service first;
robots.txt is honoured unless disabled globally.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup, Tag

from ..models import Condition, ListingType, Product, Search, parse_condition, parse_price
from .base import Source, register


def _text(node: Tag | None) -> str | None:
    return node.get_text(" ", strip=True) if node else None


@register("html")
class HtmlSource(Source):
    label = "Web page (CSS selectors)"
    description = ("Scrape any shop or classifieds search page by describing its markup with CSS selectors. "
                   "Check the site's terms first - robots.txt is honoured unless disabled in Settings.")
    fields = [
        {"name": "search_url", "label": "Search URL", "type": "text", "required": True,
         "help": "{query} and {page} are substituted, e.g. https://shop.example/search?q={query}&p={page}"},
        {"name": "selectors", "label": "Selectors", "type": "selectors", "required": True,
         "keys": ["item", "title", "link", "price", "image", "condition", "shipping", "location", "seller",
                  "seller_rating", "description"],
         "help": "'item' matches one listing; all others are relative to it. item + title are required."},
        {"name": "attributes", "label": "Extra attribute selectors", "type": "map",
         "help": "Attribute name → selector, e.g. brand → .brand"},
        {"name": "default_condition", "label": "Default condition", "type": "select", "default": "unknown",
         "choices": ["new", "used", "refurbished", "unknown"]},
        {"name": "listing_type", "label": "Listing type", "type": "select", "default": "fixed",
         "choices": ["fixed", "offer", "auction", "unknown"]},
        {"name": "currency", "label": "Currency", "type": "text", "default": "EUR"},
        {"name": "country", "label": "Country (ISO code)", "type": "text"},
        {"name": "shipping_cost", "label": "Flat shipping cost", "type": "number"},
        {"name": "max_pages", "label": "Max pages", "type": "number", "default": 1},
        {"name": "filter_locally", "label": "Keep only titles containing the query", "type": "bool",
         "help": "Automatically on when the URL has no {query}."},
        {"name": "id_attribute", "label": "Item ID attribute", "type": "text", "default": "data-id"},
    ]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_url: str = self.options["search_url"]  # e.g. https://shop.example/search?q={query}
        self.selectors: dict[str, str] = self.options["selectors"]
        if "item" not in self.selectors or "title" not in self.selectors:
            raise ValueError(f"source '{self.name}': selectors.item and selectors.title are required")
        self.currency = self.options.get("currency", "EUR")
        self.default_condition = Condition(self.options.get("default_condition", "unknown"))
        self.max_pages = int(self.options.get("max_pages", 1))
        # For listing pages without a search URL: keep only items whose title
        # contains every word of the query.
        self.filter_locally = bool(self.options.get("filter_locally", "{query}" not in self.search_url))

    def _select(self, item: Tag, field: str) -> Tag | None:
        selector = self.selectors.get(field)
        return item.select_one(selector) if selector else None

    def _attr(self, node: Tag | None, *names: str) -> str | None:
        if node is None:
            return None
        for name in names:
            if value := node.get(name):
                return value if isinstance(value, str) else " ".join(value)
        return None

    def parse_page(self, html: str, page_url: str) -> Iterator[Product]:
        soup = BeautifulSoup(html, "lxml")
        for item in soup.select(self.selectors["item"]):
            title_node = self._select(item, "title")
            title = _text(title_node)
            if not title:
                continue
            # Many shops shorten long titles ("Lenovo ThinkPa...") and keep the full one in title="".
            full = self._attr(title_node, "title")
            if full and title.rstrip().endswith(("...", "…")) and len(full) > len(title) - 3:
                title = full.strip()
            link_node = self._select(item, "link") or item.select_one("a[href]")
            href = self._attr(link_node, "href")
            url = urljoin(page_url, href) if href else page_url
            image = self._attr(self._select(item, "image"), "src", "data-src", "data-lazy-src")
            condition_text = _text(self._select(item, "condition"))
            condition = parse_condition(condition_text) if condition_text else Condition.UNKNOWN
            if condition is Condition.UNKNOWN:
                condition = parse_condition(title)
            if condition is Condition.UNKNOWN:
                condition = self.default_condition
            price_text = _text(self._select(item, "price"))
            external_id = (self._attr(item, self.options.get("id_attribute", "data-id"))
                           or hashlib.sha1(url.encode()).hexdigest()[:16])
            yield Product(
                source=self.name,
                external_id=external_id,
                title=title,
                url=url,
                price=parse_price(price_text),
                currency=self.currency,
                shipping=self._shipping(item),
                condition=condition,
                listing_type=self._listing_type(price_text or ""),
                location=_text(self._select(item, "location")),
                country=self.options.get("country"),
                seller=_text(self._select(item, "seller")),
                seller_rating=parse_price(_text(self._select(item, "seller_rating"))),
                image_url=urljoin(page_url, image) if image else None,
                description=_text(self._select(item, "description")),
                attributes={name: value for name, sel in (self.options.get("attributes") or {}).items()
                            if (value := _text(item.select_one(sel)))},
            )

    def _shipping(self, item: Tag) -> float | None:
        text = _text(self._select(item, "shipping"))
        if text is None:
            return self.options.get("shipping_cost")
        if re.search(r"free|kostenlos|gratis|versandkostenfrei", text, re.I):
            return 0.0
        return parse_price(text)

    def _listing_type(self, price_text: str) -> ListingType:
        if re.search(r"\bVB\b|verhandlungsbasis|best offer|o\.?b\.?o", price_text, re.I):
            return ListingType.OFFER
        if re.search(r"gebot|bid|auktion|auction", price_text, re.I):
            return ListingType.AUCTION
        return ListingType(self.options.get("listing_type", "fixed"))

    def search(self, search: Search) -> Iterator[Product]:
        found = 0
        for page in range(1, self.max_pages + 1):
            url = self.search_url.format(query=quote_plus(search.query), page=page)
            resp = self.http.get(url)
            page_items = list(self.parse_page(resp.text, url))
            if not page_items:
                return
            if self.filter_locally:
                terms = search.query.lower().split()
                page_items = [p for p in page_items if all(t in p.title.lower() for t in terms)]
            for product in page_items:
                yield product
                found += 1
                if found >= search.max_results:
                    return
            if "{page}" not in self.search_url:
                return
