"""eBay via the official Browse API (free developer keys: https://developer.ebay.com)."""

from __future__ import annotations

import time
from collections.abc import Iterator

from ..models import Condition, ListingType, Product, Search
from .base import Source, register

# https://developer.ebay.com/api-docs/sell/static/metadata/condition-id-values.html
CONDITION_IDS: dict[Condition, list[str]] = {
    Condition.NEW: ["1000", "1500", "1750"],
    Condition.REFURBISHED: ["2000", "2010", "2020", "2030", "2500"],
    Condition.USED: ["2750", "3000", "4000", "5000", "6000", "7000"],
}
_ID_TO_CONDITION = {cid: cond for cond, ids in CONDITION_IDS.items() for cid in ids}


@register("ebay")
class EbaySource(Source):
    label = "eBay (official Browse API)"
    description = ("Searches eBay through the official Browse API. Free keys: developer.ebay.com → "
                   "Application Keys → Production. Returns condition, shipping, seller rating and auctions.")
    fields = [
        {"name": "client_id", "label": "Client ID (App ID)", "type": "secret", "required": True,
         "default": "${EBAY_CLIENT_ID}", "help": "Use ${ENV_VAR} to keep the key in the environment."},
        {"name": "client_secret", "label": "Client secret (Cert ID)", "type": "secret", "required": True,
         "default": "${EBAY_CLIENT_SECRET}"},
        {"name": "marketplace", "label": "Marketplace", "type": "select", "default": "EBAY_DE",
         "choices": ["EBAY_DE", "EBAY_AT", "EBAY_CH", "EBAY_GB", "EBAY_US", "EBAY_FR", "EBAY_IT", "EBAY_ES",
                     "EBAY_NL", "EBAY_PL", "EBAY_AU", "EBAY_CA"]},
        {"name": "currency", "label": "Currency", "type": "text", "default": "EUR"},
        {"name": "item_location_country", "label": "Only items located in (ISO code)", "type": "text",
         "help": "e.g. DE - leave empty for all countries"},
        {"name": "sandbox", "label": "Use sandbox API", "type": "bool", "default": False},
    ]
    API = "https://api.ebay.com"
    SANDBOX_API = "https://api.sandbox.ebay.com"
    SCOPE = "https://api.ebay.com/oauth/api_scope"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base = self.SANDBOX_API if self.options.get("sandbox") else self.API
        self.marketplace = self.options.get("marketplace", "EBAY_DE")
        self.currency = self.options.get("currency", "EUR")
        self._token: str | None = None
        self._token_expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        client_id = self.options.get("client_id")
        client_secret = self.options.get("client_secret")
        if not client_id or not client_secret:
            raise RuntimeError("ebay source needs client_id and client_secret (EBAY_CLIENT_ID / EBAY_CLIENT_SECRET)")
        resp = self.http.post(
            f"{self.base}/identity/v1/oauth2/token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials", "scope": self.SCOPE},
        )
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires = time.time() + int(payload.get("expires_in", 7200))
        return self._token

    def build_filter(self, search: Search) -> str:
        parts = []
        ids = [cid for cond in search.conditions for cid in CONDITION_IDS.get(cond, [])]
        # Only restrict when not every condition is wanted, otherwise unlabelled items get dropped.
        if ids and Condition.UNKNOWN not in search.conditions:
            parts.append("conditionIds:{" + "|".join(ids) + "}")
        if country := self.options.get("item_location_country"):
            parts.append(f"itemLocationCountry:{country}")
        if search.min_price is not None or search.max_price is not None:
            lo = "" if search.min_price is None else search.min_price
            hi = "" if search.max_price is None else search.max_price
            parts.append(f"price:[{lo}..{hi}]")
            parts.append(f"priceCurrency:{self.currency}")
        return ",".join(parts)

    def parse_item(self, item: dict) -> Product:
        buying = item.get("buyingOptions") or []
        price = item.get("price") or item.get("currentBidPrice") or {}
        if "AUCTION" in buying:
            listing_type, price = ListingType.AUCTION, item.get("currentBidPrice") or price
        elif "BEST_OFFER" in buying:
            listing_type = ListingType.OFFER
        elif "FIXED_PRICE" in buying:
            listing_type = ListingType.FIXED
        else:
            listing_type = ListingType.UNKNOWN
        shipping = None
        for option in item.get("shippingOptions") or []:
            cost = (option.get("shippingCost") or {}).get("value")
            if cost is not None:
                shipping = min(float(cost), shipping if shipping is not None else float("inf"))
        location = item.get("itemLocation") or {}
        seller = item.get("seller") or {}
        categories = item.get("categories") or []
        rating = seller.get("feedbackPercentage")
        return Product(
            source=self.name,
            external_id=item["itemId"],
            title=item.get("title", ""),
            url=item.get("itemWebUrl", ""),
            price=float(price["value"]) if price.get("value") else None,
            currency=price.get("currency"),
            shipping=shipping,
            condition=_ID_TO_CONDITION.get(str(item.get("conditionId")), Condition.UNKNOWN),
            listing_type=listing_type,
            location=", ".join(v for v in (location.get("postalCode"), location.get("city")) if v) or None,
            country=location.get("country"),
            seller=seller.get("username"),
            seller_rating=float(rating) if rating else None,
            image_url=(item.get("image") or {}).get("imageUrl"),
            description=item.get("shortDescription"),
            attributes={"ebay_category": categories[0]["categoryName"]} if categories else {},
        )

    def search(self, search: Search) -> Iterator[Product]:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
        }
        params = {"q": search.query, "fieldgroups": "EXTENDED"}
        if flt := self.build_filter(search):
            params["filter"] = flt
        offset = 0
        while offset < search.max_results:
            params.update(limit=min(search.max_results - offset, 200), offset=offset)
            resp = self.http.get(f"{self.base}/buy/browse/v1/item_summary/search",
                                 params=params, headers=headers, check_robots=False)
            items = resp.json().get("itemSummaries", [])
            for item in items:
                yield self.parse_item(item)
            if len(items) < params["limit"]:
                return
            offset += len(items)
