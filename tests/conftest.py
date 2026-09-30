from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from nightcrawler.db import Database
from nightcrawler.models import Condition, ListingType, Product, Search
from nightcrawler.sources.base import Source, register


def make_product(external_id: str, title: str, price: float | None = 100.0, *, source: str = "fake",
                 condition: Condition = Condition.USED, **kw) -> Product:
    return Product(source=source, external_id=external_id, title=title, url=f"https://example.com/{external_id}",
                   price=price, currency="EUR", condition=condition, **kw)


@register("fake")
class FakeSource(Source):
    """Returns the products stored in options['products'] (list of Product)."""
    label = "Fake"

    def search(self, search: Search) -> Iterator[Product]:
        if self.options.get("fail"):
            raise RuntimeError("boom")
        for p in self.options.get("products", []):
            p.seen_at = datetime.now(UTC)
            yield p


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def search(db) -> Search:
    row = db.save_search({"name": "laptops", "query": "thinkpad", "max_price": 1000})
    return db.search_obj(row)


__all__ = ["make_product", "Condition", "ListingType"]
