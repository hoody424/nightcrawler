"""SQLite persistence: watchlists, sources, products, price history, runs, settings."""

from __future__ import annotations

import json
import sqlite3
import statistics
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .attributes import extract_attributes, numeric_value
from .models import Condition, Product, Search

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    options     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id                INTEGER PRIMARY KEY,
    name              TEXT UNIQUE NOT NULL,
    query             TEXT NOT NULL,
    conditions        TEXT NOT NULL,
    min_price         REAL,
    max_price         REAL,
    include_keywords  TEXT NOT NULL DEFAULT '[]',
    exclude_keywords  TEXT NOT NULL DEFAULT '[]',
    sources           TEXT,
    max_results       INTEGER NOT NULL DEFAULT 50,
    interval_minutes  INTEGER NOT NULL DEFAULT 60,
    enabled           INTEGER NOT NULL DEFAULT 1,
    notify            INTEGER NOT NULL DEFAULT 1,
    ai_filter         TEXT,
    last_run_at       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    key          TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    price        REAL,
    currency     TEXT,
    shipping     REAL,
    total_price  REAL GENERATED ALWAYS AS (price + COALESCE(shipping, 0)) VIRTUAL,
    condition    TEXT NOT NULL,
    listing_type TEXT NOT NULL DEFAULT 'unknown',
    location     TEXT,
    country      TEXT,
    seller       TEXT,
    seller_rating REAL,
    image_url    TEXT,
    description  TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    missed_runs  INTEGER NOT NULL DEFAULT 0,
    favorite     INTEGER NOT NULL DEFAULT 0,
    hidden       INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    ai_assessment TEXT
);
CREATE TABLE IF NOT EXISTS matches (
    search_id      INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    product_key    TEXT NOT NULL REFERENCES products(key) ON DELETE CASCADE,
    first_matched  TEXT NOT NULL,
    deal_pct       REAL,
    ai_relevant    INTEGER,
    ai_reason      TEXT,
    PRIMARY KEY (search_id, product_key)
);
CREATE TABLE IF NOT EXISTS product_attributes (
    product_key  TEXT NOT NULL REFERENCES products(key) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    value        TEXT NOT NULL,
    num_value    REAL,
    origin       TEXT NOT NULL,  -- rules | ai | source
    PRIMARY KEY (product_key, name)
);
CREATE INDEX IF NOT EXISTS idx_attr_name_value ON product_attributes(name, value);
CREATE INDEX IF NOT EXISTS idx_attr_name_num ON product_attributes(name, num_value);
CREATE TABLE IF NOT EXISTS price_history (
    product_key  TEXT NOT NULL REFERENCES products(key) ON DELETE CASCADE,
    price        REAL,
    seen_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    search_id    INTEGER REFERENCES searches(id) ON DELETE SET NULL,
    search_name  TEXT NOT NULL,
    trigger      TEXT NOT NULL,
    status       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    fetched      INTEGER NOT NULL DEFAULT 0,
    matched      INTEGER NOT NULL DEFAULT 0,
    new          INTEGER NOT NULL DEFAULT 0,
    price_drops  INTEGER NOT NULL DEFAULT 0,
    errors       TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_last_seen ON products(last_seen);
CREATE INDEX IF NOT EXISTS idx_products_source ON products(source);
CREATE INDEX IF NOT EXISTS idx_matches_product ON matches(product_key);
CREATE INDEX IF NOT EXISTS idx_history_key ON price_history(product_key, seen_at);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "notification_urls": [],          # Apprise URLs, e.g. discord://..., tgram://..., ntfy://...
    "notify_price_drop_pct": 5.0,     # alert when a price falls by at least this much
    "notify_min_deal_pct": None,      # only alert new items at least this % below the median
    "gone_after_missed_runs": 2,      # listing counts as sold/removed after N runs without it
    "retention_days": 90,             # purge gone listings after N days (0 = keep forever)
    "http_user_agent": "nightcrawler/1.0 (+https://github.com/hoody424/nightcrawler)",
    "http_delay_seconds": 2.0,
    "http_timeout_seconds": 20.0,
    "http_retries": 3,
    "respect_robots_txt": True,
    "ai_backend": "auto",             # auto | claude_code (Pro/Max subscription) | api | off
    "ai_oauth_token": "",             # from `claude setup-token`; CLAUDE_CODE_OAUTH_TOKEN env wins
    "ai_model": "",                   # empty = backend default; e.g. "sonnet", "opus", "claude-opus-5-5"
    "ai_effort": "low",
    "ai_max_calls_per_hour": 60,      # protects subscription usage limits / API spend
    "ai_extract_attributes": False,   # AI spec extraction for every new listing
    "base_url": "",                   # public URL of this UI, used for links in notifications
}

def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _loads(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value else default


class Database:
    """Thread-safe wrapper: one connection per thread, WAL mode for concurrent readers."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        # A shared in-memory DB needs a single connection (tests).
        self._shared = self._connect() if self.path == ":memory:" else None
        with self._write_lock:
            self.conn.executescript(SCHEMA)  # executescript manages its own transaction

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._connect()
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def fetchall(self, sql: str, args: Iterable = ()) -> list[dict]:
        with self._write_lock if self._shared is not None else _nullcontext():
            return [dict(r) for r in self.conn.execute(sql, tuple(args))]

    def fetchone(self, sql: str, args: Iterable = ()) -> dict | None:
        rows = self.fetchall(sql, args)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict[str, Any]:
        stored = {r["key"]: json.loads(r["value"]) for r in self.fetchall("SELECT * FROM settings")}
        return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"unknown settings: {sorted(unknown)}")
        with self.tx() as conn:
            for key, value in values.items():
                conn.execute("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                             (key, json.dumps(value)))
        return self.get_settings()

    # ------------------------------------------------------------------- sources
    @staticmethod
    def _source_row(row: dict) -> dict:
        row["enabled"] = bool(row["enabled"])
        row["options"] = _loads(row["options"], {})
        return row

    def list_sources(self) -> list[dict]:
        return [self._source_row(r) for r in self.fetchall("SELECT * FROM sources ORDER BY name")]

    def get_source(self, source_id: int) -> dict | None:
        row = self.fetchone("SELECT * FROM sources WHERE id = ?", (source_id,))
        return self._source_row(row) if row else None

    def save_source(self, data: dict, source_id: int | None = None) -> dict:
        now = utcnow()
        values = (data["name"], data["type"], int(data.get("enabled", True)),
                  json.dumps(data.get("options") or {}))
        with self.tx() as conn:
            if source_id is None:
                cur = conn.execute(
                    "INSERT INTO sources (name, type, enabled, options, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)", (*values, now, now))
                source_id = cur.lastrowid
            else:
                conn.execute("UPDATE sources SET name=?, type=?, enabled=?, options=?, updated_at=? WHERE id=?",
                             (*values, now, source_id))
        return self.get_source(source_id)

    def delete_source(self, source_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    # ------------------------------------------------------------------ searches
    @staticmethod
    def _search_row(row: dict) -> dict:
        row["conditions"] = _loads(row["conditions"], [])
        row["include_keywords"] = _loads(row["include_keywords"], [])
        row["exclude_keywords"] = _loads(row["exclude_keywords"], [])
        row["sources"] = _loads(row["sources"])
        row["enabled"] = bool(row["enabled"])
        row["notify"] = bool(row["notify"])
        return row

    def list_searches(self) -> list[dict]:
        rows = self.fetchall("""
            SELECT s.*,
              (SELECT COUNT(*) FROM matches m JOIN products p ON p.key = m.product_key
                 WHERE m.search_id = s.id AND p.hidden = 0) AS product_count,
              (SELECT MIN(p.price) FROM matches m JOIN products p ON p.key = m.product_key
                 WHERE m.search_id = s.id AND p.hidden = 0 AND p.missed_runs < ?
                   AND COALESCE(m.ai_relevant, 1) = 1) AS best_price,
              (SELECT status FROM runs r WHERE r.search_id = s.id ORDER BY r.id DESC LIMIT 1) AS last_status
            FROM searches s ORDER BY s.name COLLATE NOCASE""", (self.get_settings()["gone_after_missed_runs"],))
        return [self._search_row(r) for r in rows]

    def get_search(self, search_id: int) -> dict | None:
        row = self.fetchone("SELECT * FROM searches WHERE id = ?", (search_id,))
        return self._search_row(row) if row else None

    def save_search(self, data: dict, search_id: int | None = None) -> dict:
        now = utcnow()
        values = (
            data["name"], data["query"],
            json.dumps(data.get("conditions") or [c.value for c in Condition]),
            data.get("min_price"), data.get("max_price"),
            json.dumps([k.lower() for k in data.get("include_keywords") or []]),
            json.dumps([k.lower() for k in data.get("exclude_keywords") or []]),
            json.dumps(data["sources"]) if data.get("sources") else None,
            int(data.get("max_results") or 50), int(data.get("interval_minutes") or 60),
            int(data.get("enabled", True)), int(data.get("notify", True)),
            (data.get("ai_filter") or "").strip() or None,
        )
        cols = ("name, query, conditions, min_price, max_price, include_keywords, exclude_keywords, "
                "sources, max_results, interval_minutes, enabled, notify, ai_filter")
        with self.tx() as conn:
            if search_id is None:
                cur = conn.execute(
                    f"INSERT INTO searches ({cols}, created_at, updated_at)"
                    f" VALUES ({', '.join('?' * 15)})", (*values, now, now))
                search_id = cur.lastrowid
            else:
                assignments = ", ".join(f"{c.strip()} = ?" for c in cols.split(","))
                conn.execute(f"UPDATE searches SET {assignments}, updated_at = ? WHERE id = ?",
                             (*values, now, search_id))
        return self.get_search(search_id)

    def delete_search(self, search_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
            # Drop products no watchlist refers to any more (unless favourited).
            conn.execute("""DELETE FROM products WHERE favorite = 0
                            AND key NOT IN (SELECT product_key FROM matches)""")

    def search_obj(self, row: dict) -> Search:
        return Search(
            id=row["id"], name=row["name"], query=row["query"],
            conditions=[Condition(c) for c in row["conditions"]],
            min_price=row["min_price"], max_price=row["max_price"],
            include_keywords=row["include_keywords"], exclude_keywords=row["exclude_keywords"],
            sources=row["sources"], max_results=row["max_results"],
            interval_minutes=row["interval_minutes"], enabled=row["enabled"],
            notify=row["notify"], ai_filter=row["ai_filter"],
        )

    def due_searches(self, now: datetime | None = None) -> list[Search]:
        now = now or datetime.now(UTC)
        due = []
        for row in self.list_searches():
            if not row["enabled"]:
                continue
            last = row["last_run_at"]
            if last is None or datetime.fromisoformat(last) + timedelta(minutes=row["interval_minutes"]) <= now:
                due.append(self.search_obj(row))
        return due

    def mark_search_run(self, search_id: int, when: str) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE searches SET last_run_at = ? WHERE id = ?", (when, search_id))

    # ---------------------------------------------------------------------- runs
    def start_run(self, search: Search, trigger: str) -> int:
        with self.tx() as conn:
            cur = conn.execute(
                "INSERT INTO runs (search_id, search_name, trigger, status, started_at) VALUES (?, ?, ?, 'running', ?)",
                (search.id, search.name, trigger, utcnow()))
            return cur.lastrowid

    def finish_run(self, run_id: int, *, status: str, fetched: int, matched: int, new: int,
                   price_drops: int, errors: list[str]) -> None:
        with self.tx() as conn:
            conn.execute(
                """UPDATE runs SET status=?, finished_at=?, fetched=?, matched=?, new=?, price_drops=?, errors=?
                   WHERE id=?""",
                (status, utcnow(), fetched, matched, new, price_drops, json.dumps(errors), run_id))

    def list_runs(self, limit: int = 100, search_id: int | None = None) -> list[dict]:
        sql, args = "SELECT * FROM runs", []
        if search_id is not None:
            sql += " WHERE search_id = ?"
            args.append(search_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = self.fetchall(sql, args)
        for r in rows:
            r["errors"] = _loads(r["errors"], [])
        return rows

    def fail_stale_runs(self) -> None:
        """Runs left 'running' by a crash/restart can never finish."""
        with self.tx() as conn:
            conn.execute("UPDATE runs SET status='error', finished_at=?, errors=? WHERE status='running'",
                         (utcnow(), json.dumps(["interrupted (process restarted)"])))

    # ------------------------------------------------------------------ products
    def upsert_products(self, search: Search,
                        products: list[Product]) -> tuple[list[Product], list[tuple[Product, float]]]:
        """Store products matched by `search`.

        Returns (new_for_this_watchlist, price_drops[(product, old_price)]).
        """
        new: list[Product] = []
        drops: list[tuple[Product, float]] = []
        with self.tx() as conn:
            for p in products:
                now = p.seen_at.isoformat(timespec="seconds")
                fields = (p.title, p.url, p.price, p.currency, p.shipping, p.condition.value, p.listing_type.value,
                          p.location, p.country, p.seller, p.seller_rating, p.image_url, p.description)
                row = conn.execute("SELECT price FROM products WHERE key = ?", (p.key,)).fetchone()
                if row is None:
                    conn.execute(
                        """INSERT INTO products (key, source, external_id, title, url, price, currency, shipping,
                               condition, listing_type, location, country, seller, seller_rating, image_url,
                               description, first_seen, last_seen)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (p.key, p.source, p.external_id, *fields, now, now))
                    conn.execute("INSERT INTO price_history VALUES (?, ?, ?)", (p.key, p.price, now))
                else:
                    conn.execute(
                        """UPDATE products SET title=?, url=?, price=?, currency=?, shipping=?, condition=?,
                               listing_type=?, location=?, country=?, seller=?, seller_rating=?,
                               image_url=COALESCE(?, image_url), description=COALESCE(?, description),
                               last_seen=?, missed_runs=0
                           WHERE key=?""",
                        (*fields, now, p.key))
                    old = row["price"]
                    if old != p.price:
                        conn.execute("INSERT INTO price_history VALUES (?, ?, ?)", (p.key, p.price, now))
                        if old is not None and p.price is not None and p.price < old:
                            drops.append((p, old))
                self._write_attributes(conn, p)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO matches (search_id, product_key, first_matched) VALUES (?, ?, ?)",
                    (search.id, p.key, now))
                if cur.rowcount:
                    new.append(p)  # new listing, or known listing that is new for this watchlist
        return new, drops

    @staticmethod
    def _write_attributes(conn: sqlite3.Connection, p: Product) -> None:
        # Precedence: source-provided > AI-extracted > rule-based.
        conn.execute("DELETE FROM product_attributes WHERE product_key = ? AND origin != 'ai'", (p.key,))
        for name, value in extract_attributes(p.title, p.description).items():
            conn.execute("INSERT OR IGNORE INTO product_attributes VALUES (?, ?, ?, ?, 'rules')",
                         (p.key, name, value, numeric_value(name, value)))
        for name, value in p.attributes.items():
            if value:
                # Shop categories ("Notebooks & Zubehör") are less consistent than ours: fill gaps only.
                verb = "INSERT OR IGNORE" if name == "category" else "INSERT OR REPLACE"
                conn.execute(f"{verb} INTO product_attributes VALUES (?, ?, ?, ?, 'source')",
                             (p.key, name, str(value), numeric_value(name, str(value))))

    def set_ai_attributes(self, key: str, attributes: dict[str, str]) -> None:
        with self.tx() as conn:
            for name, value in attributes.items():
                conn.execute(
                    """INSERT INTO product_attributes VALUES (?, ?, ?, ?, 'ai')
                       ON CONFLICT(product_key, name) DO UPDATE SET value = excluded.value,
                           num_value = excluded.num_value, origin = 'ai'
                       WHERE product_attributes.origin != 'source'""",
                    (key, name, value, numeric_value(name, value)))

    def attributes_of(self, keys: list[str]) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {k: {} for k in keys}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            for r in self.fetchall(
                    f"SELECT product_key, name, value FROM product_attributes WHERE product_key IN "
                    f"({', '.join('?' * len(chunk))})", chunk):
                out[r["product_key"]][r["name"]] = r["value"]
        return out

    def mark_missed(self, search_id: int, source: str, run_started: str) -> None:
        """Listings of this watchlist+source that the latest successful fetch didn't return."""
        with self.tx() as conn:
            conn.execute(
                """UPDATE products SET missed_runs = missed_runs + 1
                   WHERE source = ? AND last_seen < ?
                     AND key IN (SELECT product_key FROM matches WHERE search_id = ?)""",
                (source, run_started, search_id))

    def update_deal_scores(self, search_id: int) -> None:
        """deal_pct = how far below the median of comparable active listings (same condition) a price is."""
        gone_after = self.get_settings()["gone_after_missed_runs"]
        rows = self.fetchall(
            """SELECT p.key, p.price, p.condition, p.currency FROM matches m JOIN products p ON p.key = m.product_key
               WHERE m.search_id = ? AND p.price IS NOT NULL AND p.price > 0
                 AND p.missed_runs < ? AND COALESCE(m.ai_relevant, 1) = 1""", (search_id, gone_after))
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            groups.setdefault((r["condition"], r["currency"]), []).append(r)
        with self.tx() as conn:
            conn.execute("UPDATE matches SET deal_pct = NULL WHERE search_id = ?", (search_id,))
            for items in groups.values():
                if len(items) < 3:  # a median of 1-2 listings says nothing
                    continue
                median = statistics.median(i["price"] for i in items)
                for i in items:
                    conn.execute("UPDATE matches SET deal_pct = ? WHERE search_id = ? AND product_key = ?",
                                 (round((median - i["price"]) / median * 100, 1), search_id, i["key"]))

    def set_ai_verdicts(self, search_id: int, verdicts: dict[str, tuple[bool, str]]) -> None:
        with self.tx() as conn:
            for key, (relevant, reason) in verdicts.items():
                conn.execute(
                    "UPDATE matches SET ai_relevant = ?, ai_reason = ? WHERE search_id = ? AND product_key = ?",
                    (int(relevant), reason, search_id, key))

    def deal_pct(self, search_id: int, key: str) -> float | None:
        row = self.fetchone("SELECT deal_pct FROM matches WHERE search_id = ? AND product_key = ?", (search_id, key))
        return row["deal_pct"] if row else None

    def get_product(self, key: str) -> dict | None:
        row = self.fetchone("SELECT * FROM products WHERE key = ?", (key,))
        if not row:
            return None
        row["favorite"], row["hidden"] = bool(row["favorite"]), bool(row["hidden"])
        row["gone"] = row["missed_runs"] >= self.get_settings()["gone_after_missed_runs"]
        row["attributes"] = self.attributes_of([key])[key]
        row["history"] = self.fetchall(
            "SELECT price, seen_at FROM price_history WHERE product_key = ? ORDER BY seen_at", (key,))
        row["matches"] = self.fetchall(
            """SELECT m.search_id, s.name AS search_name, m.first_matched, m.deal_pct, m.ai_relevant, m.ai_reason
               FROM matches m JOIN searches s ON s.id = m.search_id WHERE m.product_key = ?""", (key,))
        return row

    def update_product(self, key: str, *, favorite: bool | None = None, hidden: bool | None = None,
                       note: str | None = None) -> dict | None:
        sets, args = [], []
        for col, val in (("favorite", favorite), ("hidden", hidden)):
            if val is not None:
                sets.append(f"{col} = ?")
                args.append(int(val))
        if note is not None:
            sets.append("note = ?")
            args.append(note or None)
        if sets:
            with self.tx() as conn:
                conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE key = ?", (*args, key))
        return self.get_product(key)

    def purge(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self.tx() as conn:
            cur = conn.execute("DELETE FROM products WHERE favorite = 0 AND last_seen < ?", (cutoff,))
            conn.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
            return cur.rowcount

    # --------------------------------------------------------------------- stats
    def stats(self) -> dict:
        s = self.get_settings()
        gone_after = s["gone_after_missed_runs"]
        day_ago = (datetime.now(UTC) - timedelta(hours=24)).isoformat(timespec="seconds")
        visible = ("p.hidden = 0 AND EXISTS (SELECT 1 FROM matches m WHERE m.product_key = p.key"
                   " AND COALESCE(m.ai_relevant, 1) = 1)")
        one = lambda sql, *a: self.fetchone(sql, a)["n"]  # noqa: E731
        by_condition = {r["condition"]: r["n"] for r in self.fetchall(
            f"SELECT p.condition, COUNT(*) AS n FROM products p WHERE {visible} AND p.missed_runs < ? GROUP BY 1",
            (gone_after,))}
        by_source = self.fetchall(
            f"""SELECT p.source, COUNT(*) AS n, SUM(p.first_seen >= ?) AS new_24h FROM products p
                WHERE {visible} AND p.missed_runs < ? GROUP BY 1 ORDER BY n DESC""", (day_ago, gone_after))
        daily = self.fetchall(
            f"""SELECT substr(p.first_seen, 1, 10) AS day, COUNT(*) AS n FROM products p
                WHERE {visible} AND p.first_seen >= ? GROUP BY 1 ORDER BY 1""",
            ((datetime.now(UTC) - timedelta(days=13)).date().isoformat(),))
        drops_24h = one(
            """SELECT COUNT(DISTINCT h.product_key) AS n FROM price_history h
               WHERE h.seen_at >= ? AND h.price < (SELECT h2.price FROM price_history h2
                 WHERE h2.product_key = h.product_key AND h2.seen_at < h.seen_at ORDER BY h2.seen_at DESC LIMIT 1)""",
            day_ago)
        return {
            "active": one(f"SELECT COUNT(*) AS n FROM products p WHERE {visible} AND p.missed_runs < ?", gone_after),
            "new_24h": one(f"SELECT COUNT(*) AS n FROM products p WHERE {visible} AND p.first_seen >= ?", day_ago),
            "gone": one(f"SELECT COUNT(*) AS n FROM products p WHERE {visible} AND p.missed_runs >= ?", gone_after),
            "favorites": one("SELECT COUNT(*) AS n FROM products WHERE favorite = 1"),
            "price_drops_24h": drops_24h,
            "watchlists": one("SELECT COUNT(*) AS n FROM searches WHERE enabled = 1"),
            "sources": one("SELECT COUNT(*) AS n FROM sources WHERE enabled = 1"),
            "runs_24h": one("SELECT COUNT(*) AS n FROM runs WHERE started_at >= ?", day_ago),
            "failed_runs_24h": one(
                "SELECT COUNT(*) AS n FROM runs WHERE started_at >= ? AND status = 'error'", day_ago),
            "by_condition": by_condition,
            "by_source": by_source,
            "daily_new": daily,
        }

    def is_empty(self) -> bool:
        return not self.fetchone("SELECT 1 AS x FROM searches") and not self.fetchone("SELECT 1 AS x FROM sources")


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
