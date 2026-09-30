"""Runs a watchlist against its sources: fetch, filter, store, analyse, notify."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import notify
from .ai import AI, get_ai
from .config import HttpSettings
from .db import Database, utcnow
from .http import HttpClient, RobotsDisallowed
from .models import Product, Search
from .sources import Source, build_source

log = logging.getLogger(__name__)


def matches(product: Product, search: Search) -> bool:
    if product.condition not in search.conditions:
        return False
    if product.price is not None:
        if search.min_price is not None and product.price < search.min_price:
            return False
        if search.max_price is not None and product.price > search.max_price:
            return False
    elif search.min_price is not None or search.max_price is not None:
        return False  # can't verify a price constraint without a price
    title = product.title.lower()
    if any(k not in title for k in search.include_keywords):
        return False
    if any(k in title for k in search.exclude_keywords):
        return False
    return True


@dataclass
class RunResult:
    run_id: int
    status: str = "ok"
    fetched: int = 0
    matched: int = 0
    new: list[Product] = field(default_factory=list)
    price_drops: list[tuple[Product, float]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class Crawler:
    def __init__(self, db: Database, ai: AI | None = None):
        self.db = db
        self._ai = ai  # injected in tests; otherwise resolved from settings per run

    def _sources(self, http: HttpClient) -> list[Source]:
        sources = []
        for row in self.db.list_sources():
            if row["enabled"]:
                sources.append(build_source(row["name"], row["type"], row["options"], http))
        return sources

    def run_search(self, search: Search, trigger: str = "schedule") -> RunResult:
        settings = self.db.get_settings()
        result = RunResult(run_id=self.db.start_run(search, trigger))
        started = utcnow()
        self.db.mark_search_run(search.id, started)
        http = HttpClient(HttpSettings.from_settings(settings))

        try:
            sources = [s for s in self._sources(http) if search.matches_source(s.name)]
        except ValueError as exc:
            sources, result.errors = [], [str(exc)]
        if not sources and not result.errors:
            result.errors.append("no enabled source applies to this watchlist")

        succeeded = 0
        for source in sources:
            try:
                found = list(source.search(search))
            except RobotsDisallowed as exc:
                result.errors.append(f"{source.name}: {exc}")
                continue
            except Exception as exc:  # one broken source must not stop the others
                log.exception("source %s failed for %r", source.name, search.name)
                result.errors.append(f"{source.name}: {type(exc).__name__}: {exc}")
                continue
            succeeded += 1
            kept = [p for p in found if matches(p, search)]
            new, drops = self.db.upsert_products(search, kept)
            self.db.mark_missed(search.id, source.name, started)
            result.fetched += len(found)
            result.matched += len(kept)
            result.new += new
            result.price_drops += drops
            log.info("%-14s %-24s fetched=%d matched=%d new=%d drops=%d",
                     source.name, search.name, len(found), len(kept), len(new), len(drops))

        self._analyze(search, result, settings)
        self.db.update_deal_scores(search.id)
        if search.notify:
            self._notify(search, result, settings)

        if not sources:
            result.status = "error" if any("unknown type" in e for e in result.errors) else "skipped"
        elif succeeded == len(sources):
            result.status = "ok" if not result.errors else "partial"
        else:
            result.status = "partial" if succeeded else "error"
        self.db.finish_run(result.run_id, status=result.status, fetched=result.fetched, matched=result.matched,
                           new=len(result.new), price_drops=len(result.price_drops), errors=result.errors)
        return result

    def _analyze(self, search: Search, result: RunResult, settings: dict) -> None:
        wants_ai = bool(search.ai_filter) or settings["ai_extract_attributes"]
        if not result.new or not wants_ai:
            return
        ai = self._ai or get_ai(settings)
        if ai is None:
            if search.ai_filter:
                result.errors.append("AI filter set but no Claude connection configured - listings kept unfiltered")
            return
        try:
            verdicts = ai.analyze_listings(result.new, search.ai_filter)
        except Exception as exc:
            log.exception("AI analysis failed")
            result.errors.append(f"AI analysis failed: {type(exc).__name__}: {exc}")
            return
        if search.ai_filter:
            self.db.set_ai_verdicts(search.id, {k: (v.relevant, v.reason) for k, v in verdicts.items()})
        for key, verdict in verdicts.items():
            if verdict.attributes:
                self.db.set_ai_attributes(key, verdict.attributes)

    def _notify(self, search: Search, result: RunResult, settings: dict) -> None:
        urls = settings["notification_urls"]
        if not urls:
            return
        min_deal = settings["notify_min_deal_pct"]
        new = []
        rejected = {r["product_key"] for r in self.db.fetchall(
            "SELECT product_key FROM matches WHERE search_id = ? AND ai_relevant = 0", (search.id,))}
        for p in result.new:
            if p.key in rejected:
                continue
            deal = self.db.deal_pct(search.id, p.key)
            if min_deal is not None and (deal is None or deal < min_deal):
                continue
            new.append((p, deal))
        threshold = float(settings["notify_price_drop_pct"] or 0)
        drops = [(p, old) for p, old in result.price_drops
                 if p.key not in rejected and (old - p.price) / old * 100 >= threshold]
        if not new and not drops:
            return
        title, body = notify.format_alert(search.name, new, drops, settings.get("base_url", ""))
        ok, message = notify.send(urls, title, body)
        if not ok:
            result.errors.append(f"notification: {message}")
