"""Polite HTTP client: per-host rate limiting, retries and robots.txt checks."""

from __future__ import annotations

import logging
import threading
import time
from urllib import robotparser
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import HttpSettings

log = logging.getLogger(__name__)


class RobotsDisallowed(Exception):
    pass


class HttpClient:
    def __init__(self, settings: HttpSettings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        })
        retry = Retry(
            total=settings.retries,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _throttle(self, host: str) -> None:
        with self._lock:
            wait = self._last_request.get(host, 0) + self.settings.delay_seconds - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()

    def _robots_for(self, url: str) -> robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            parser = robotparser.RobotFileParser()
            try:
                resp = self.session.get(f"{base}/robots.txt", timeout=self.settings.timeout_seconds)
                if resp.status_code >= 400:
                    parser = None  # no robots.txt -> everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except requests.RequestException as exc:
                log.warning("could not fetch robots.txt for %s: %s", base, exc)
                parser = None
            self._robots[base] = parser
        return self._robots[base]

    def check_robots(self, url: str) -> None:
        if not self.settings.respect_robots_txt:
            return
        parser = self._robots_for(url)
        if parser is not None and not parser.can_fetch(self.settings.user_agent, url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

    def get(self, url: str, *, check_robots: bool = True, **kwargs) -> requests.Response:
        if check_robots:
            self.check_robots(url)
        self._throttle(urlsplit(url).netloc)
        kwargs.setdefault("timeout", self.settings.timeout_seconds)
        resp = self.session.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        self._throttle(urlsplit(url).netloc)
        kwargs.setdefault("timeout", self.settings.timeout_seconds)
        resp = self.session.post(url, **kwargs)
        resp.raise_for_status()
        return resp
