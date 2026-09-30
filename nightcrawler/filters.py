"""Faceted product filtering (Geizhals-style).

Values inside one filter group are OR-ed, groups are AND-ed. Facet counts for a
group are computed with every *other* active filter applied but not the group's
own selection ("disjunctive faceting"), so users always see the alternatives
they could switch to and how many results each would give.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .attributes import ATTRIBUTE_BY_NAME, ATTRIBUTES
from .db import Database

SortKey = Literal["newest", "price_asc", "price_desc", "deal", "last_seen", "title", "seller_rating", "drop"]


class ProductFilter(BaseModel):
    q: str | None = None
    search_ids: list[int] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    listing_types: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    price_min: float | None = None
    price_max: float | None = None
    include_shipping: bool = False  # price filter + sort on price incl. shipping
    free_shipping: bool = False
    seller_rating_min: float | None = None
    min_deal_pct: float | None = None
    price_dropped: bool = False
    new_within_hours: float | None = None
    status: Literal["active", "gone", "all"] = "active"
    favorites: bool = False
    include_hidden: bool = False
    include_rejected: bool = False  # listings the AI filter judged irrelevant
    attrs: dict[str, list[str]] = Field(default_factory=dict)  # attribute -> accepted values (OR)
    ranges: dict[str, tuple[float | None, float | None]] = Field(default_factory=dict)
    flags: dict[str, Literal["only", "exclude"]] = Field(default_factory=dict)
    sort: SortKey = "newest"
    page: int = Field(1, ge=1)
    per_page: int = Field(48, ge=1, le=500)
    facets: bool = True


SORT_SQL = {
    "newest": "p.first_seen DESC",
    "last_seen": "p.last_seen DESC",
    "price_asc": "{price} IS NULL, {price} ASC",
    "price_desc": "{price} IS NULL, {price} DESC",
    "deal": "deal_pct IS NULL, deal_pct DESC",
    "title": "p.title COLLATE NOCASE ASC",
    "seller_rating": "p.seller_rating IS NULL, p.seller_rating DESC",
    "drop": "drop_pct IS NULL, drop_pct DESC",
}
FIRST_PRICE = "(SELECT h.price FROM price_history h WHERE h.product_key = p.key ORDER BY h.seen_at LIMIT 1)"
SELLER_RATING_STEPS = [99.5, 99, 98, 95, 90]


class Query:
    def __init__(self, db: Database, f: ProductFilter):
        self.db, self.f = db, f
        self.gone_after = db.get_settings()["gone_after_missed_runs"]
        self.price_expr = "p.total_price" if f.include_shipping else "p.price"

    # -------------------------------------------------------------- building
    def _match_cond(self, alias: str = "m", *, with_searches: bool = True) -> tuple[str, list]:
        cond, args = [f"{alias}.product_key = p.key"], []
        if with_searches and self.f.search_ids:
            cond.append(f"{alias}.search_id IN ({', '.join('?' * len(self.f.search_ids))})")
            args += self.f.search_ids
        if not self.f.include_rejected:
            cond.append(f"COALESCE({alias}.ai_relevant, 1) = 1")
        return " AND ".join(cond), args

    def deal_expr(self) -> tuple[str, list]:
        cond, args = self._match_cond("md")
        return f"(SELECT MAX(md.deal_pct) FROM matches md WHERE {cond})", args

    def where(self, exclude: str | None = None) -> tuple[str, list]:
        """WHERE clause for all active filters, optionally leaving out one facet dimension."""
        f, clauses, args = self.f, [], []

        def add(dimension: str | None, sql: str, *values: Any) -> None:
            if dimension is None or dimension != exclude:
                clauses.append(sql)
                args.extend(values)

        cond, cargs = self._match_cond(with_searches=exclude != "search")
        add(None, f"EXISTS (SELECT 1 FROM matches m WHERE {cond})", *cargs)
        if f.q:
            for word in f.q.split():
                add(None, "(p.title LIKE ? OR p.note LIKE ? OR p.seller LIKE ?)", *[f"%{word}%"] * 3)
        column_filters = (("condition", "condition", f.conditions), ("source", "source", f.sources),
                          ("listing_type", "listing_type", f.listing_types), ("country", "country", f.countries))
        for dim, col, values in column_filters:
            if values:
                add(dim, f"p.{col} IN ({', '.join('?' * len(values))})", *values)
        if f.price_min is not None:
            add("price", f"{self.price_expr} >= ?", f.price_min)
        if f.price_max is not None:
            add("price", f"{self.price_expr} <= ?", f.price_max)
        if f.free_shipping:
            add("shipping", "p.shipping = 0")
        if f.seller_rating_min is not None:
            add("seller_rating", "p.seller_rating >= ?", f.seller_rating_min)
        if f.min_deal_pct is not None:
            deal, dargs = self.deal_expr()
            add("deal", f"{deal} >= ?", *dargs, f.min_deal_pct)
        if f.price_dropped:
            add(None, f"p.price < {FIRST_PRICE}")
        if f.new_within_hours:
            since = datetime.now(UTC) - timedelta(hours=f.new_within_hours)
            add(None, "p.first_seen >= ?", since.isoformat(timespec="seconds"))
        if f.status == "active":
            add(None, "p.missed_runs < ?", self.gone_after)
        elif f.status == "gone":
            add(None, "p.missed_runs >= ?", self.gone_after)
        if f.favorites:
            add(None, "p.favorite = 1")
        if not f.include_hidden:
            add(None, "p.hidden = 0")
        for name, values in f.attrs.items():
            if values and name in ATTRIBUTE_BY_NAME:
                add(f"attr:{name}",
                    f"EXISTS (SELECT 1 FROM product_attributes a WHERE a.product_key = p.key AND a.name = ?"
                    f" AND a.value IN ({', '.join('?' * len(values))}))", name, *values)
        for name, (lo, hi) in f.ranges.items():
            if name not in ATTRIBUTE_BY_NAME or (lo is None and hi is None):
                continue
            sql = "EXISTS (SELECT 1 FROM product_attributes a WHERE a.product_key = p.key AND a.name = ?"
            vals: list[Any] = [name]
            if lo is not None:
                sql += " AND a.num_value >= ?"
                vals.append(lo)
            if hi is not None:
                sql += " AND a.num_value <= ?"
                vals.append(hi)
            add(f"attr:{name}", sql + ")", *vals)
        for name, mode in f.flags.items():
            if name in ATTRIBUTE_BY_NAME:
                neg = "NOT " if mode == "exclude" else ""
                add(f"flag:{name}", f"{neg}EXISTS (SELECT 1 FROM product_attributes a WHERE a.product_key = p.key"
                                    f" AND a.name = ? AND a.value = 'yes')", name)
        return " AND ".join(clauses) or "1=1", args

    # --------------------------------------------------------------- results
    def results(self) -> tuple[list[dict], int]:
        f = self.f
        where, args = self.where()
        total = self.db.fetchone(f"SELECT COUNT(*) AS n FROM products p WHERE {where}", args)["n"]
        deal, dargs = self.deal_expr()
        mcond, margs = self._match_cond("ms")
        order = SORT_SQL[f.sort].format(price=self.price_expr)
        rows = self.db.fetchall(
            f"""SELECT p.*, {deal} AS deal_pct, {FIRST_PRICE} AS first_price,
                   (SELECT GROUP_CONCAT(s.name, ', ') FROM matches ms JOIN searches s ON s.id = ms.search_id
                      WHERE {mcond}) AS searches,
                   (SELECT mr.ai_reason FROM matches mr WHERE mr.product_key = p.key AND mr.ai_reason IS NOT NULL
                      LIMIT 1) AS ai_reason,
                   (SELECT json_group_object(a.name, a.value) FROM product_attributes a
                      WHERE a.product_key = p.key) AS attributes,
                   CASE WHEN {FIRST_PRICE} > p.price
                        THEN ROUND(({FIRST_PRICE} - p.price) * 100.0 / {FIRST_PRICE}, 1) END AS drop_pct,
                   p.missed_runs >= ? AS gone
                FROM products p WHERE {where}
                ORDER BY {order}, p.key LIMIT ? OFFSET ?""",
            [*dargs, *margs, self.gone_after, *args, f.per_page, (f.page - 1) * f.per_page])
        for r in rows:
            r["attributes"] = json.loads(r["attributes"] or "{}")
            r["favorite"], r["hidden"], r["gone"] = bool(r["favorite"]), bool(r["hidden"]), bool(r["gone"])
        return rows, total

    # ---------------------------------------------------------------- facets
    def _column_facet(self, dimension: str, column: str) -> list[dict]:
        where, args = self.where(exclude=dimension)
        return self.db.fetchall(
            f"""SELECT p.{column} AS value, COUNT(*) AS count FROM products p
                WHERE {where} AND p.{column} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1""", args)

    def _search_facet(self) -> list[dict]:
        where, args = self.where(exclude="search")
        cond, cargs = self._match_cond("mf", with_searches=False)
        return self.db.fetchall(
            f"""SELECT s.id AS value, s.name AS label, COUNT(DISTINCT p.key) AS count
                FROM products p JOIN matches mf ON {cond} JOIN searches s ON s.id = mf.search_id
                WHERE {where} GROUP BY s.id ORDER BY count DESC, s.name""", [*cargs, *args])

    def _attribute_facet(self, name: str, numeric: bool) -> dict:
        where, args = self.where(exclude=f"attr:{name}")
        order = "a.num_value" if numeric else "count DESC, a.value COLLATE NOCASE"
        values = self.db.fetchall(
            f"""SELECT a.value AS value, COUNT(*) AS count, MIN(a.num_value) AS num FROM products p
                JOIN product_attributes a ON a.product_key = p.key AND a.name = ?
                WHERE {where} GROUP BY a.value ORDER BY {order} LIMIT 300""", [name, *args])
        facet: dict[str, Any] = {"values": values}
        if numeric and values:
            nums = [v["num"] for v in values if v["num"] is not None]
            facet.update(min=min(nums, default=None), max=max(nums, default=None))
        return facet

    def _flag_facet(self, name: str) -> dict:
        where, args = self.where(exclude=f"flag:{name}")
        row = self.db.fetchone(
            f"""SELECT COUNT(*) AS total,
                   SUM(EXISTS (SELECT 1 FROM product_attributes a WHERE a.product_key = p.key
                       AND a.name = ? AND a.value = 'yes')) AS yes
                FROM products p WHERE {where}""", [name, *args])
        yes = row["yes"] or 0
        return {"only": yes, "exclude": row["total"] - yes}

    def _price_facet(self, buckets: int = 24) -> dict:
        where, args = self.where(exclude="price")
        price = self.price_expr
        row = self.db.fetchone(
            f"SELECT MIN({price}) AS lo, MAX({price}) AS hi FROM products p WHERE {where} AND {price} IS NOT NULL",
            args)
        lo, hi = row["lo"], row["hi"]
        if lo is None:
            return {"min": None, "max": None, "histogram": []}
        lo, hi = math.floor(lo), math.ceil(hi)
        width = max((hi - lo) / buckets, 1e-9)
        counts = {r["b"]: r["n"] for r in self.db.fetchall(
            f"""SELECT MIN(CAST(({price} - ?) / ? AS INTEGER), ?) AS b, COUNT(*) AS n FROM products p
                WHERE {where} AND {price} IS NOT NULL GROUP BY 1""", [lo, width, buckets - 1, *args])}
        hist = [{"from": round(lo + i * width, 2), "to": round(lo + (i + 1) * width, 2), "count": counts.get(i, 0)}
                for i in range(buckets)]
        return {"min": lo, "max": hi, "histogram": hist}

    def _seller_rating_facet(self) -> list[dict]:
        where, args = self.where(exclude="seller_rating")
        cols = ", ".join(f"SUM(p.seller_rating >= {s}) AS r{i}" for i, s in enumerate(SELLER_RATING_STEPS))
        row = self.db.fetchone(f"SELECT {cols} FROM products p WHERE {where}", args)
        return [{"value": s, "count": row[f"r{i}"] or 0} for i, s in enumerate(SELLER_RATING_STEPS)]

    def _shipping_facet(self) -> dict:
        where, args = self.where(exclude="shipping")
        row = self.db.fetchone(f"SELECT SUM(p.shipping = 0) AS free FROM products p WHERE {where}", args)
        return {"free": row["free"] or 0}

    def _deal_facet(self) -> list[dict]:
        where, args = self.where(exclude="deal")
        deal, dargs = self.deal_expr()
        steps = [10, 20, 30, 40]
        cols = ", ".join(f"SUM(d >= {s}) AS d{s}" for s in steps)
        row = self.db.fetchone(
            f"SELECT {cols} FROM (SELECT {deal} AS d FROM products p WHERE {where})", [*dargs, *args])
        return [{"value": s, "count": row[f"d{s}"] or 0} for s in steps]

    def facets(self) -> dict:
        attributes = {}
        for a in ATTRIBUTES:
            if a.kind == "flag":
                attributes[a.name] = self._flag_facet(a.name)
            else:
                attributes[a.name] = self._attribute_facet(a.name, numeric=a.kind == "number")
        return {
            "searches": self._search_facet(),
            "conditions": self._column_facet("condition", "condition"),
            "sources": self._column_facet("source", "source"),
            "listing_types": self._column_facet("listing_type", "listing_type"),
            "countries": self._column_facet("country", "country"),
            "price": self._price_facet(),
            "shipping": self._shipping_facet(),
            "seller_rating": self._seller_rating_facet(),
            "deal": self._deal_facet(),
            "attributes": attributes,
        }


def attribute_definitions() -> list[dict]:
    return [{"name": a.name, "label": a.label, "kind": a.kind, "group": a.group, "unit": a.unit} for a in ATTRIBUTES]


def search_products(db: Database, f: ProductFilter) -> dict:
    query = Query(db, f)
    items, total = query.results()
    return {
        "items": items,
        "total": total,
        "page": f.page,
        "pages": max(1, math.ceil(total / f.per_page)),
        "facets": query.facets() if f.facets else None,
    }
