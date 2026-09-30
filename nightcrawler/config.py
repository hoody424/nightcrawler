"""Environment/YAML helpers.

Watchlists, sources and settings live in the database and are managed in the web
UI. A YAML file can seed a fresh database (first start) or be imported later.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .db import Database

SECRET_SETTINGS = {"ai_oauth_token"}  # never exported
_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    """Replace ${VAR} / ${VAR:-default} in strings so secrets can stay in the environment."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


@dataclass
class HttpSettings:
    user_agent: str = "nightcrawler/1.0 (+https://github.com/hoody424/nightcrawler)"
    delay_seconds: float = 2.0
    timeout_seconds: float = 20.0
    retries: int = 3
    respect_robots_txt: bool = True

    @classmethod
    def from_settings(cls, s: dict[str, Any]) -> HttpSettings:
        return cls(
            user_agent=s["http_user_agent"],
            delay_seconds=float(s["http_delay_seconds"]),
            timeout_seconds=float(s["http_timeout_seconds"]),
            retries=int(s["http_retries"]),
            respect_robots_txt=bool(s["respect_robots_txt"]),
        )


def import_yaml(db: Database, path: str | Path, *, overwrite: bool = False) -> dict[str, int]:
    """Import `settings`, `sources` and `searches` from a YAML file into the database.

    Existing entries (matched by name) are kept unless overwrite=True. ${VAR}
    references in source options are stored as-is and resolved at runtime.
    """
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    counts = {"sources": 0, "searches": 0, "settings": 0}
    if settings := raw.get("settings"):
        db.update_settings(expand_env(settings))
        counts["settings"] = len(settings)

    existing_sources = {s["name"]: s["id"] for s in db.list_sources()}
    for name, cfg in (raw.get("sources") or {}).items():
        cfg = dict(cfg or {})
        if name in existing_sources and not overwrite:
            continue
        enabled = expand_env(cfg.pop("enabled", True))
        data = {
            "name": name,
            "type": cfg.pop("type", name),
            "enabled": str(enabled).lower() not in ("false", "0", "no", ""),
            "options": cfg,
        }
        db.save_source(data, existing_sources.get(name))
        counts["sources"] += 1

    existing_searches = {s["name"]: s["id"] for s in db.list_searches()}
    for entry in raw.get("searches") or []:
        entry = dict(entry)
        entry.setdefault("name", entry["query"])
        conditions = entry.get("conditions") or "any"
        if isinstance(conditions, str):
            conditions = [conditions]
        entry["conditions"] = None if "any" in conditions else [c.lower() for c in conditions]
        if entry["name"] in existing_searches and not overwrite:
            continue
        db.save_search(entry, existing_searches.get(entry["name"]))
        counts["searches"] += 1
    return counts


def export_yaml(db: Database) -> str:
    searches = []
    for s in db.list_searches():
        entry = {k: s[k] for k in ("name", "query", "conditions", "min_price", "max_price", "include_keywords",
                                   "exclude_keywords", "sources", "max_results", "interval_minutes", "enabled",
                                   "notify", "ai_filter") if s[k] not in (None, [], "")}
        searches.append(entry)
    sources = {s["name"]: {"type": s["type"], "enabled": s["enabled"], **s["options"]} for s in db.list_sources()}
    settings = {k: v for k, v in db.get_settings().items() if k not in SECRET_SETTINGS}
    return yaml.safe_dump({"settings": settings, "sources": sources, "searches": searches},
                          sort_keys=False, allow_unicode=True)
