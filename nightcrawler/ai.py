"""AI features, powered by Claude.

Two interchangeable backends:

* ``claude_code`` - your **Claude Pro/Max subscription** through the official Claude
  Code CLI in headless mode (``claude -p``). Authenticate once with
  ``claude setup-token`` and provide the token as CLAUDE_CODE_OAUTH_TOKEN (or paste it
  in Settings), or run ``claude auth login`` inside the container.
* ``api`` - an Anthropic API key (ANTHROPIC_API_KEY), billed per token.

Features: relevance filtering + spec extraction for new listings, natural-language
search → filters, watchlist drafting, deal assessment and CSS-selector suggestions.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .attributes import ATTRIBUTES
from .models import Product

log = logging.getLogger(__name__)

BATCH_SIZE = 25
ATTRIBUTE_NAMES = [a.name for a in ATTRIBUTES]
API_DEFAULT_MODEL = "claude-opus-5-5"


class AIError(RuntimeError):
    pass


class AIUnavailable(AIError):
    pass


# ============================================================ backends


class Backend:
    name = ""

    def structured(self, system: str, prompt: str, schema: dict, effort: str) -> dict:
        raise NotImplementedError


class ClaudeCodeBackend(Backend):
    """Runs `claude -p` with structured output. Uses the subscription login, never an API key."""

    name = "claude_code"

    def __init__(self, model: str = "", oauth_token: str = "", timeout: float = 600):
        self.model = model
        self.oauth_token = oauth_token
        self.timeout = timeout

    @staticmethod
    def cli() -> str | None:
        return shutil.which("claude")

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # An API key would take precedence over the subscription login and bill the API instead.
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        if self.oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token
        env.setdefault("DISABLE_AUTOUPDATER", "1")
        env.setdefault("DISABLE_TELEMETRY", "1")
        return env

    def structured(self, system: str, prompt: str, schema: dict, effort: str) -> dict:
        cli = self.cli()
        if not cli:
            raise AIUnavailable("Claude Code CLI not found - use the Docker image or "
                                "`npm i -g @anthropic-ai/claude-code`")
        cmd = [cli, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
               "--system-prompt", system, "--tools", "", "--strict-mcp-config", "--no-session-persistence",
               "--effort", effort]
        if self.model:
            cmd += ["--model", self.model]
        # Empty working directory: no CLAUDE.md or project settings get picked up.
        with tempfile.TemporaryDirectory(prefix="nightcrawler-ai-") as cwd:
            try:
                proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd,
                                      env=self._env(), timeout=self.timeout)
            except subprocess.TimeoutExpired:
                raise AIError(f"Claude Code timed out after {self.timeout:.0f}s") from None
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            detail = (proc.stderr or proc.stdout).strip()[-500:]
            raise AIError(f"Claude Code failed (exit {proc.returncode}): {detail}") from None
        if out.get("is_error") or out.get("subtype") != "success":
            detail = str(out.get("result") or out.get("subtype"))
            if "not logged in" in detail.lower() or "/login" in detail:
                raise AIUnavailable("Claude subscription not connected: run `claude setup-token` and paste the token "
                                    "in Settings → AI (or set CLAUDE_CODE_OAUTH_TOKEN).")
            raise AIError(f"Claude Code error: {detail[:500]}")
        data = out.get("structured_output")
        if data is None:  # older CLI without structured_output: result holds the JSON text
            data = json.loads(out.get("result") or "{}")
        return data

    def auth_status(self) -> dict:
        cli = self.cli()
        if not cli:
            return {"installed": False}
        try:
            proc = subprocess.run([cli, "auth", "status", "--json"], capture_output=True, text=True,
                                  env=self._env(), timeout=30)
            status = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"raw": proc.stdout.strip()}
        except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
            status = {"error": str(exc)}
        return {"installed": True, "token_configured": bool(self.oauth_token), **status}


class ApiBackend(Backend):
    name = "api"

    def __init__(self, model: str = ""):
        import anthropic

        self.model = model or API_DEFAULT_MODEL
        self.client = anthropic.Anthropic()

    def structured(self, system: str, prompt: str, schema: dict, effort: str) -> dict:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # On a safety decline, let the API retry on its recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise AIError("request declined by the model")
        if response.stop_reason == "max_tokens":
            raise AIError("response truncated (max_tokens)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return json.loads(text)


def _subscription_configured(token: str) -> bool:
    if token or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return (config_dir / ".credentials.json").exists()


def resolve_backend(settings: dict) -> Backend | None:
    """Pick the backend from settings. 'auto' prefers the subscription over an API key."""
    choice = settings.get("ai_backend", "auto")
    model = settings.get("ai_model") or ""
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or settings.get("ai_oauth_token") or ""
    if choice == "off":
        return None
    if choice == "claude_code" or (choice == "auto" and ClaudeCodeBackend.cli() and _subscription_configured(token)):
        return ClaudeCodeBackend(model=model, oauth_token=token)
    if choice == "api" or (choice == "auto" and (os.environ.get("ANTHROPIC_API_KEY")
                                                 or os.environ.get("ANTHROPIC_AUTH_TOKEN"))):
        return ApiBackend(model=model if model.startswith("claude-") else "")
    return None


# ============================================================ features

LISTING_SYSTEM = f"""You analyse second-hand and retail marketplace listings for a deal-finder app.

For every listing you receive, return one result with the same id:
- relevant: if a watchlist rule is given, true only when the listing is what the rule asks for. Listings \
that are accessories, spare parts, empty boxes, "wanted/suche" posts, trades or services are not relevant \
unless the rule explicitly allows them. Without a rule, always true.
- reason: one short sentence explaining the decision.
- attributes: facts that are stated or unambiguous from the title/description. Allowed names: \
{", ".join(ATTRIBUTE_NAMES)}. Numbers are plain numbers without units (storage_gb and ram_gb in GB, \
1 TB = 1000; screen_in in inches; refresh_hz in Hz). Flags (original_box, warranty, invoice, defective) use \
the value "yes" and only when the listing says so - "keine Garantie" means no warranty. Use a canonical \
model name for "model" (e.g. "iPhone 13 Pro", "ThinkPad T14 Gen 2") and English category names. \
Omit anything you are unsure about."""

LISTING_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "relevant": {"type": "boolean"},
            "reason": {"type": "string"},
            "attributes": {"type": "array", "items": {
                "type": "object",
                "properties": {"name": {"type": "string", "enum": ATTRIBUTE_NAMES}, "value": {"type": "string"}},
                "required": ["name", "value"], "additionalProperties": False}},
        },
        "required": ["id", "relevant", "reason", "attributes"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}

FILTER_SYSTEM = """You turn a shopper's request (any language) into filters for a product search UI \
similar to Geizhals. Only set filters the request actually implies. Put remaining free-text words that \
are not covered by a filter into "q" (keep it short, e.g. a model name). Prices are in the shop currency. \
Use attribute values exactly as listed in the available values when one fits. "defective" should be \
excluded when the user wants working items. Explain the applied filters in one short sentence in the \
user's language."""

WATCHLIST_SYSTEM = """You set up a watchlist for a crawler that searches marketplaces (eBay, shops, \
classifieds) for new and used products. From the user's description (any language) produce: a short \
name, a concise marketplace search query (the words sellers use in titles), accepted conditions, an \
optional price range, include keywords that every title must contain (use sparingly), exclude keywords \
that filter obvious junk (e.g. "defekt", "suche", "tausch", "hülle", "case", "box only") and an \
ai_filter rule in plain language describing precisely which listings are wanted."""

DEAL_SYSTEM = """You are an experienced second-hand market expert helping a buyer judge a listing. \
Use the listing data, its price history and comparable listings from the same search. Consider the \
condition, completeness, market price level, seller signals, and scam indicators (price far below \
market, off-platform payment requests, stock photos, brand-new seller, vague descriptions). Be concrete \
and brief. Answer in the language of the listing."""

SELECTOR_SYSTEM = """You write CSS selectors for a scraper. Given the HTML of a search-results page, \
find the repeating element that represents one listing ("item") and selectors relative to it for the \
fields. Prefer stable class names or data attributes over positional selectors. Leave a field empty \
when the page has no such data. "link" must select the <a> leading to the listing page, "image" an \
<img>. Mention in "notes" anything the user should verify."""


@dataclass
class Verdict:
    relevant: bool
    reason: str
    attributes: dict[str, str] = field(default_factory=dict)


class AI:
    """Feature layer with a rolling hourly call limit (protects subscription usage limits)."""

    def __init__(self, backend: Backend, effort: str = "low", max_calls_per_hour: int = 60):
        self.backend = backend
        self.effort = effort
        self.max_calls_per_hour = max_calls_per_hour
        self._calls: deque[float] = _CALL_LOG
        self._lock = _CALL_LOCK

    def _call(self, system: str, prompt: str, schema: dict, effort: str | None = None) -> dict:
        with self._lock:
            now = time.time()
            while self._calls and now - self._calls[0] > 3600:
                self._calls.popleft()
            if self.max_calls_per_hour and len(self._calls) >= self.max_calls_per_hour:
                raise AIError(f"hourly AI call limit reached ({self.max_calls_per_hour}); raise it in Settings")
            self._calls.append(now)
        return self.backend.structured(system, prompt, schema, effort or self.effort)

    # ------------------------------------------------ listing analysis
    def analyze_listings(self, products: list[Product], rule: str | None) -> dict[str, Verdict]:
        verdicts: dict[str, Verdict] = {}
        for i in range(0, len(products), BATCH_SIZE):
            batch = products[i:i + BATCH_SIZE]
            ids = {str(n): p.key for n, p in enumerate(batch)}
            listings = [{"id": str(n), "title": p.title, "price": p.price, "currency": p.currency,
                         "condition": p.condition.value, "description": (p.description or "")[:400] or None}
                        for n, p in enumerate(batch)]
            prompt = (f"Watchlist rule: {rule}" if rule else "No watchlist rule - mark everything relevant.") + \
                "\n\nListings:\n" + json.dumps(listings, ensure_ascii=False, indent=1)
            data = self._call(LISTING_SYSTEM, prompt, LISTING_SCHEMA)
            for item in data.get("items", []):
                if key := ids.get(str(item.get("id"))):
                    attrs = {a["name"]: str(a["value"]).strip() for a in item.get("attributes", [])
                             if a.get("name") in ATTRIBUTE_NAMES and str(a.get("value", "")).strip()}
                    verdicts[key] = Verdict(bool(item.get("relevant", True)), str(item.get("reason", ""))[:300], attrs)
        return verdicts

    # ------------------------------------------------ natural-language search
    def parse_filter(self, text: str, facet_values: dict[str, list[str]], sources: list[str]) -> dict:
        schema = {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "conditions": {"type": "array", "items": {"type": "string", "enum": ["new", "used", "refurbished"]}},
                "price_min": {"type": "number"},
                "price_max": {"type": "number"},
                "include_shipping": {"type": "boolean"},
                "free_shipping": {"type": "boolean"},
                "seller_rating_min": {"type": "number"},
                "listing_types": {"type": "array", "items": {"type": "string", "enum": ["fixed", "auction", "offer"]}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "countries": {"type": "array", "items": {"type": "string"}},
                "attrs": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string", "enum": [a.name for a in ATTRIBUTES if a.kind != "flag"]},
                    "values": {"type": "array", "items": {"type": "string"}}},
                    "required": ["name", "values"], "additionalProperties": False}},
                "ranges": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string", "enum": [a.name for a in ATTRIBUTES if a.kind == "number"]},
                    "min": {"type": "number"}, "max": {"type": "number"}},
                    "required": ["name"], "additionalProperties": False}},
                "flags": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string", "enum": [a.name for a in ATTRIBUTES if a.kind == "flag"]},
                    "mode": {"type": "string", "enum": ["only", "exclude"]}},
                    "required": ["name", "mode"], "additionalProperties": False}},
                "sort": {"type": "string", "enum": ["newest", "price_asc", "price_desc", "deal", "seller_rating"]},
                "explanation": {"type": "string"},
            },
            "required": ["explanation"],
            "additionalProperties": False,
        }
        attr_help = "\n".join(
            f"- {a.name} ({a.label}{', ' + a.unit if a.unit else ''}, {a.kind})"
            + (f": {', '.join(facet_values.get(a.name, [])[:40])}" if facet_values.get(a.name) else "")
            for a in ATTRIBUTES)
        prompt = (f"Available attributes and known values:\n{attr_help}\n\nSources: {', '.join(sources)}\n\n"
                  f"Request: {text}")
        data = self._call(FILTER_SYSTEM, prompt, schema)
        result: dict[str, Any] = {k: v for k, v in data.items() if k not in ("attrs", "ranges", "flags")}
        result["attrs"] = {a["name"]: a["values"] for a in data.get("attrs", []) if a.get("values")}
        result["ranges"] = {r["name"]: [r.get("min"), r.get("max")] for r in data.get("ranges", [])}
        result["flags"] = {f["name"]: f["mode"] for f in data.get("flags", [])}
        return result

    # ------------------------------------------------ watchlist drafting
    def draft_watchlist(self, text: str) -> dict:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "query": {"type": "string"},
                "conditions": {"type": "array", "items": {"type": "string",
                                                          "enum": ["new", "used", "refurbished", "unknown"]}},
                "min_price": {"type": "number"},
                "max_price": {"type": "number"},
                "include_keywords": {"type": "array", "items": {"type": "string"}},
                "exclude_keywords": {"type": "array", "items": {"type": "string"}},
                "ai_filter": {"type": "string"},
            },
            "required": ["name", "query", "conditions", "include_keywords", "exclude_keywords", "ai_filter"],
            "additionalProperties": False,
        }
        return self._call(WATCHLIST_SYSTEM, text, schema, effort="medium")

    # ------------------------------------------------ deal assessment
    def assess_deal(self, product: dict, comparables: list[dict]) -> dict:
        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["great", "good", "fair", "overpriced", "suspicious"]},
                "score": {"type": "integer", "description": "0 = avoid, 100 = outstanding deal"},
                "summary": {"type": "string"},
                "fair_price": {"type": "number"},
                "pros": {"type": "array", "items": {"type": "string"}},
                "cons": {"type": "array", "items": {"type": "string"}},
                "red_flags": {"type": "array", "items": {"type": "string"}},
                "questions_for_seller": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["verdict", "score", "summary", "pros", "cons", "red_flags", "questions_for_seller"],
            "additionalProperties": False,
        }
        listing = {k: product.get(k) for k in ("title", "price", "currency", "shipping", "condition", "listing_type",
                                               "location", "country", "seller", "seller_rating", "description",
                                               "first_seen", "attributes", "history")}
        prompt = (f"Listing:\n{json.dumps(listing, ensure_ascii=False, indent=1, default=str)}\n\n"
                  f"Comparable active listings ({len(comparables)}):\n"
                  f"{json.dumps(comparables, ensure_ascii=False, indent=1, default=str)}")
        return self._call(DEAL_SYSTEM, prompt, schema, effort="medium")

    # ------------------------------------------------ selector suggestions
    def suggest_selectors(self, url: str, html: str) -> dict:
        keys = ["item", "title", "link", "price", "image", "condition", "shipping", "location", "seller",
                "description"]
        schema = {
            "type": "object",
            "properties": {**{k: {"type": "string"} for k in keys}, "notes": {"type": "string"}},
            "required": [*keys, "notes"],
            "additionalProperties": False,
        }
        prompt = f"Page URL: {url}\n\nHTML (scripts/styles removed):\n{html}"
        return self._call(SELECTOR_SYSTEM, prompt, schema, effort="medium")


_CALL_LOG: deque[float] = deque()
_CALL_LOCK = threading.Lock()


def get_ai(settings: dict) -> AI | None:
    backend = resolve_backend(settings)
    if backend is None:
        return None
    return AI(backend, effort=settings.get("ai_effort") or "low",
              max_calls_per_hour=int(settings.get("ai_max_calls_per_hour") or 0))


def ai_status(settings: dict) -> dict:
    backend = resolve_backend(settings)
    cli = ClaudeCodeBackend.cli()
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or settings.get("ai_oauth_token") or ""
    return {
        "backend": backend.name if backend else None,
        "configured_backend": settings.get("ai_backend", "auto"),
        "claude_cli_installed": bool(cli),
        "subscription_configured": _subscription_configured(token),
        "token_from_env": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
        "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "calls_last_hour": sum(1 for t in _CALL_LOG if time.time() - t <= 3600),
        "max_calls_per_hour": settings.get("ai_max_calls_per_hour"),
    }
