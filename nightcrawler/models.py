"""Core data types shared by all sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Condition(StrEnum):
    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"
    UNKNOWN = "unknown"


# Keyword hints (English + German) used to guess a condition from free text.
_CONDITION_HINTS: list[tuple[Condition, re.Pattern[str]]] = [
    (Condition.REFURBISHED, re.compile(
        r"\b(refurbished|renewed|generalüberholt|aufbereitet|wiederaufbereitet|b-?ware)\b", re.I)),
    (Condition.USED, re.compile(
        r"\b(used|pre-?owned|second[- ]?hand|like new|wie neu|neuwertig|gebraucht|getragen|vintage|defekt|"
        r"for parts)\b", re.I)),
    (Condition.NEW, re.compile(
        r"\b(new|brand[- ]new|neu|originalverpackt|ovp|sealed|unopened)\b", re.I)),
]


def parse_condition(text: str | None) -> Condition:
    """Normalise a free-text condition label ("Gebraucht", "Pre-owned", ...)."""
    if not text:
        return Condition.UNKNOWN
    for condition, pattern in _CONDITION_HINTS:
        if pattern.search(text):
            return condition
    return Condition.UNKNOWN


_PRICE_RE = re.compile(r"(\d{1,3}(?:[.,\s']\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)")


def parse_price(text: str | float | int | None) -> float | None:
    """Extract a price from strings like "1.299,00 €", "$1,299.99" or "EUR 45"."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = _PRICE_RE.search(text.replace(" ", " "))
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace("'", "")
    # Decide which separator is the decimal one: the last one followed by 1-2 digits.
    last_sep = max(raw.rfind(","), raw.rfind("."))
    if last_sep != -1 and len(raw) - last_sep - 1 in (1, 2):
        integer, decimal = raw[:last_sep], raw[last_sep + 1:]
    else:
        integer, decimal = raw, ""
    integer = integer.replace(",", "").replace(".", "")
    try:
        return float(f"{integer}.{decimal}" if decimal else integer)
    except ValueError:
        return None


class ListingType(StrEnum):
    FIXED = "fixed"          # buy it now / shop price
    AUCTION = "auction"
    OFFER = "offer"          # negotiable / best offer / classifieds "VB"
    UNKNOWN = "unknown"


@dataclass
class Product:
    source: str
    external_id: str
    title: str
    url: str
    price: float | None = None
    currency: str | None = None
    shipping: float | None = None  # None = unknown, 0 = free
    condition: Condition = Condition.UNKNOWN
    listing_type: ListingType = ListingType.UNKNOWN
    location: str | None = None
    country: str | None = None  # ISO 3166 alpha-2
    seller: str | None = None
    seller_rating: float | None = None  # positive feedback in percent
    image_url: str | None = None
    description: str | None = None  # short snippet, used for attribute extraction
    # Structured specs straight from the source (brand, category, ...). Merged with
    # extracted attributes; source-provided values win.
    attributes: dict[str, str] = field(default_factory=dict)
    seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"


@dataclass
class Search:
    """A watchlist entry: what to look for and how to filter it."""

    name: str
    query: str
    id: int | None = None
    conditions: list[Condition] = field(default_factory=lambda: list(Condition))
    min_price: float | None = None
    max_price: float | None = None
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    sources: list[str] | None = None  # None = every enabled source
    max_results: int = 50
    interval_minutes: int = 60
    enabled: bool = True
    notify: bool = True
    ai_filter: str | None = None  # natural-language relevance rule, needs ANTHROPIC_API_KEY

    def matches_source(self, source_name: str) -> bool:
        return not self.sources or source_name in self.sources
