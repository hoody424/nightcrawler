"""Background scheduler: runs due watchlists and manual "run now" requests."""

from __future__ import annotations

import logging
import queue
import threading
import time

from .crawler import Crawler
from .db import Database

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, db: Database, crawler: Crawler | None = None, tick_seconds: float = 20):
        self.db = db
        self.crawler = crawler or Crawler(db)
        self.tick_seconds = tick_seconds
        self._queue: queue.Queue[tuple[int, str]] = queue.Queue()
        self._queued: set[int] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_purge = 0.0
        self.paused = False
        self.current: dict | None = None  # {"search_id", "name", "started"}

    def start(self) -> None:
        self.db.fail_stale_runs()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        self._queue.put((-1, "stop"))
        if self._thread:
            self._thread.join(timeout)

    def enqueue(self, search_id: int, trigger: str = "manual") -> bool:
        if search_id in self._queued or (self.current and self.current["search_id"] == search_id):
            return False
        self._queued.add(search_id)
        self._queue.put((search_id, trigger))
        return True

    def status(self) -> dict:
        return {"running": self.current, "queued": sorted(self._queued), "paused": self.paused}

    def _run(self, search_id: int, trigger: str) -> None:
        row = self.db.get_search(search_id)
        if row is None:
            return
        search = self.db.search_obj(row)
        self.current = {"search_id": search.id, "name": search.name, "started": time.time()}
        try:
            self.crawler.run_search(search, trigger)
        except Exception:
            log.exception("run of %r crashed", search.name)
        finally:
            self.current = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                search_id, trigger = self._queue.get(timeout=self.tick_seconds)
            except queue.Empty:
                search_id, trigger = None, "schedule"
            if self._stop.is_set():
                break
            if search_id is not None and search_id >= 0:
                self._queued.discard(search_id)
                self._run(search_id, trigger)
                continue
            if not self.paused:
                for search in self.db.due_searches():
                    if self._stop.is_set() or not self._queue.empty():
                        break  # manual requests take priority
                    self._run(search.id, "schedule")
            self._maybe_purge()

    def _maybe_purge(self) -> None:
        if time.time() - self._last_purge < 3600:
            return
        self._last_purge = time.time()
        removed = self.db.purge(int(self.db.get_settings()["retention_days"]))
        if removed:
            log.info("purged %d old listings", removed)
