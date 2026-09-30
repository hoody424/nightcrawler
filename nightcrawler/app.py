"""FastAPI application: REST API + single-page web UI + background scheduler."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from bs4 import BeautifulSoup
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import __version__, notify
from .ai import AIError, ai_status, get_ai
from .attributes import extract_attributes
from .config import SECRET_SETTINGS, HttpSettings, export_yaml, import_yaml
from .db import DEFAULT_SETTINGS, Database
from .filters import ProductFilter, Query, attribute_definitions, search_products
from .http import HttpClient
from .models import Condition, Search
from .scheduler import Scheduler
from .sources import build_source, source_types

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
MASK = "••••••••"


# ------------------------------------------------------------------ schemas
class SearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=300)
    conditions: list[Condition] = Field(default_factory=lambda: list(Condition))
    min_price: float | None = Field(None, ge=0)
    max_price: float | None = Field(None, ge=0)
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    sources: list[str] | None = None
    max_results: int = Field(50, ge=1, le=1000)
    interval_minutes: int = Field(60, ge=5, le=60 * 24 * 7)
    enabled: bool = True
    notify: bool = True
    ai_filter: str | None = Field(None, max_length=2000)

    @field_validator("include_keywords", "exclude_keywords")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return [k.strip() for k in v if k.strip()]


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w.-]+$")
    type: str
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


class SourceTest(BaseModel):
    source: SourceIn
    query: str = "test"
    limit: int = Field(10, ge=1, le=50)


class ProductPatch(BaseModel):
    favorite: bool | None = None
    hidden: bool | None = None
    note: str | None = Field(None, max_length=2000)


# --------------------------------------------------------------------- auth
def _auth_middleware(app: FastAPI) -> None:
    user, password = os.environ.get("NIGHTCRAWLER_USERNAME"), os.environ.get("NIGHTCRAWLER_PASSWORD")
    if not (user and password):
        return

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                given_user, _, given_pw = base64.b64decode(header[6:]).decode().partition(":")
            except ValueError:
                given_user = given_pw = ""
            if secrets.compare_digest(given_user, user) and secrets.compare_digest(given_pw, password):
                return await call_next(request)
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="nightcrawler"'})


def _clean_html(html: str, limit: int = 80_000) -> tuple[str, bool]:
    """Strip a page down to structure for selector suggestions."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "head", "link", "meta", "template"]):
        tag.decompose()
    keep = {"class", "id", "href", "src", "data-src", "itemprop", "itemtype", "alt", "title"}
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in keep or k.startswith("data-")}
    text = re.sub(r"\s+", " ", str(soup.body or soup))
    return (text[:limit], len(text) > limit)


# ---------------------------------------------------------------------- app
def create_app(db_path: str, *, config_path: str | None = None, run_scheduler: bool = True) -> FastAPI:
    db = Database(db_path)
    scheduler = Scheduler(db)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if config_path and Path(config_path).exists() and db.is_empty():
            counts = import_yaml(db, config_path)
            log.info("seeded database from %s: %s", config_path, counts)
        if run_scheduler:
            scheduler.start()
        yield
        scheduler.stop()

    app = FastAPI(title="nightcrawler", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.db, app.state.scheduler = db, scheduler
    _auth_middleware(app)

    def settings_public() -> dict:
        s = db.get_settings()
        for k in SECRET_SETTINGS:
            s[k] = MASK if s.get(k) else ""
        return s

    def require_ai():
        ai = get_ai(db.get_settings())
        if ai is None:
            raise HTTPException(409, "No Claude connection configured - see Settings → AI")
        return ai

    def ai_call(fn, *args):
        try:
            return fn(*args)
        except AIError as exc:
            raise HTTPException(502, str(exc)) from exc

    # ------------------------------------------------------------- meta
    @app.get("/health", include_in_schema=False)
    def health():
        return PlainTextResponse("ok")

    @app.get("/api/meta")
    def meta():
        return {"version": __version__, "attributes": attribute_definitions(), "source_types": source_types(),
                "conditions": [c.value for c in Condition], "ai": ai_status(db.get_settings())}

    @app.get("/api/stats")
    def stats():
        return {**db.stats(), "scheduler": scheduler.status()}

    @app.get("/api/status")
    def status():
        return scheduler.status()

    # --------------------------------------------------------- products
    @app.post("/api/products/search")
    def products_search(f: ProductFilter):
        return search_products(db, f)

    @app.get("/api/products/{key:path}")
    def product_get(key: str):
        product = db.get_product(key)
        if not product:
            raise HTTPException(404, "product not found")
        product["ai_assessment"] = json.loads(product["ai_assessment"]) if product.get("ai_assessment") else None
        return product

    @app.patch("/api/products/{key:path}")
    def product_patch(key: str, patch: ProductPatch):
        product = db.update_product(key, **patch.model_dump())
        if not product:
            raise HTTPException(404, "product not found")
        return product

    @app.post("/api/compare")
    def compare(keys: list[str] = Body(..., embed=True, max_length=8)):
        return [p for k in keys if (p := db.get_product(k))]

    @app.post("/api/products/{key:path}/assess")
    def product_assess(key: str):
        ai = require_ai()
        product = db.get_product(key)
        if not product:
            raise HTTPException(404, "product not found")
        search_ids = [m["search_id"] for m in product["matches"]]
        comparables, _ = Query(db, ProductFilter(search_ids=search_ids, conditions=[product["condition"]],
                                                 sort="price_asc", per_page=25, facets=False)).results()
        comparables = [{k: c.get(k) for k in ("title", "price", "shipping", "condition", "attributes")}
                       for c in comparables if c["key"] != key]
        assessment = ai_call(ai.assess_deal, product, comparables)
        with db.tx() as conn:
            conn.execute("UPDATE products SET ai_assessment = ? WHERE key = ?", (json.dumps(assessment), key))
        return assessment

    @app.get("/api/export")
    def export(format: Literal["csv", "json"] = "csv", filter: str = "{}"):
        f = ProductFilter.model_validate({**json.loads(filter), "per_page": 500, "facets": False})
        rows: list[dict] = []
        page = 1
        while True:
            items, total = Query(db, f.model_copy(update={"page": page})).results()
            rows += items
            if len(rows) >= total or not items or page >= 100:
                break
            page += 1
        if format == "json":
            return JSONResponse(rows, headers={"Content-Disposition": "attachment; filename=nightcrawler.json"})
        attr_names = sorted({a for r in rows for a in r["attributes"]})
        base = ["title", "price", "shipping", "total_price", "currency", "condition", "listing_type", "source",
                "seller", "seller_rating", "location", "country", "deal_pct", "searches", "first_seen", "last_seen",
                "gone", "favorite", "note", "url"]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(base + attr_names)
        for r in rows:
            writer.writerow([r.get(c) for c in base] + [r["attributes"].get(a, "") for a in attr_names])
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=nightcrawler.csv"})

    # --------------------------------------------------------- watchlists
    @app.get("/api/searches")
    def searches_list():
        return db.list_searches()

    @app.post("/api/searches", status_code=201)
    def searches_create(data: SearchIn):
        if any(s["name"] == data.name for s in db.list_searches()):
            raise HTTPException(409, "a watchlist with this name exists")
        row = db.save_search(data.model_dump(mode="json"))
        scheduler.enqueue(row["id"], "created")
        return row

    @app.get("/api/searches/{search_id}")
    def searches_get(search_id: int):
        row = db.get_search(search_id)
        if not row:
            raise HTTPException(404, "watchlist not found")
        return row

    @app.put("/api/searches/{search_id}")
    def searches_update(search_id: int, data: SearchIn):
        if not db.get_search(search_id):
            raise HTTPException(404, "watchlist not found")
        return db.save_search(data.model_dump(mode="json"), search_id)

    @app.delete("/api/searches/{search_id}", status_code=204)
    def searches_delete(search_id: int):
        db.delete_search(search_id)

    @app.post("/api/searches/{search_id}/run", status_code=202)
    def searches_run(search_id: int):
        if not db.get_search(search_id):
            raise HTTPException(404, "watchlist not found")
        return {"queued": scheduler.enqueue(search_id, "manual")}

    @app.post("/api/run-all", status_code=202)
    def run_all():
        queued = [s["id"] for s in db.list_searches() if s["enabled"] and scheduler.enqueue(s["id"], "manual")]
        return {"queued": queued}

    @app.post("/api/scheduler/{action}")
    def scheduler_toggle(action: Literal["pause", "resume"]):
        scheduler.paused = action == "pause"
        return scheduler.status()

    # ------------------------------------------------------------ sources
    @app.get("/api/sources")
    def sources_list():
        return db.list_sources()

    @app.post("/api/sources", status_code=201)
    def sources_create(data: SourceIn):
        if any(s["name"] == data.name for s in db.list_sources()):
            raise HTTPException(409, "a source with this name exists")
        return db.save_source(data.model_dump())

    @app.put("/api/sources/{source_id}")
    def sources_update(source_id: int, data: SourceIn):
        if not db.get_source(source_id):
            raise HTTPException(404, "source not found")
        return db.save_source(data.model_dump(), source_id)

    @app.delete("/api/sources/{source_id}", status_code=204)
    def sources_delete(source_id: int):
        db.delete_source(source_id)

    @app.post("/api/sources/test")
    def sources_test(req: SourceTest):
        http = HttpClient(HttpSettings.from_settings(db.get_settings()))
        try:
            source = build_source(req.source.name, req.source.type, req.source.options, http)
            items = []
            for p in source.search(Search(name="test", query=req.query, max_results=req.limit)):
                items.append({**{k: getattr(p, k) for k in ("title", "url", "price", "currency", "shipping",
                                                            "location", "country", "seller", "seller_rating",
                                                            "image_url")},
                              "condition": p.condition.value, "listing_type": p.listing_type.value,
                              "attributes": {**extract_attributes(p.title, p.description), **p.attributes}})
                if len(items) >= req.limit:
                    break
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "items": []}
        return {"ok": True, "items": items}

    # ----------------------------------------------------------------- runs
    @app.get("/api/runs")
    def runs(limit: int = 100, search_id: int | None = None):
        return db.list_runs(limit=min(limit, 500), search_id=search_id)

    # ------------------------------------------------------------- settings
    @app.get("/api/settings")
    def settings_get():
        return settings_public()

    @app.put("/api/settings")
    def settings_put(values: dict[str, Any]):
        values = {k: v for k, v in values.items() if not (k in SECRET_SETTINGS and v == MASK)}
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise HTTPException(422, f"unknown settings: {sorted(unknown)}")
        db.update_settings(values)
        return settings_public()

    @app.post("/api/settings/test-notification")
    def settings_test_notification(urls: list[str] | None = Body(None, embed=True)):
        ok, message = notify.send(urls or db.get_settings()["notification_urls"], "nightcrawler test",
                                  "✅ Notifications are working.")
        return {"ok": ok, "message": message}

    @app.get("/api/config/export")
    def config_export():
        return PlainTextResponse(export_yaml(db), media_type="application/yaml",
                                 headers={"Content-Disposition": "attachment; filename=nightcrawler.yaml"})

    @app.post("/api/config/import")
    async def config_import(request: Request, overwrite: bool = False):
        body = await request.body()
        tmp = Path(db.path).with_suffix(".import.yaml") if db.path != ":memory:" else Path("/tmp/nc-import.yaml")
        tmp.write_bytes(body)
        try:
            return import_yaml(db, tmp, overwrite=overwrite)
        except Exception as exc:
            raise HTTPException(422, f"invalid config: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------- AI
    @app.get("/api/ai/status")
    def ai_status_get():
        return ai_status(db.get_settings())

    @app.post("/api/ai/test")
    def ai_test():
        ai = require_ai()
        result = ai_call(ai.backend.structured, "Reply with ok=true.", "Connection test.",
                         {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
                          "additionalProperties": False}, "low")
        return {"ok": bool(result.get("ok")), "backend": ai.backend.name}

    @app.post("/api/ai/parse-filter")
    def ai_parse_filter(text: str = Body(..., embed=True, max_length=1000)):
        ai = require_ai()
        facets = Query(db, ProductFilter(per_page=1)).facets()["attributes"]
        known = {name: [v["value"] for v in facet.get("values", [])] for name, facet in facets.items()}
        return ai_call(ai.parse_filter, text, known, [s["name"] for s in db.list_sources()])

    @app.post("/api/ai/draft-watchlist")
    def ai_draft_watchlist(text: str = Body(..., embed=True, max_length=2000)):
        return ai_call(require_ai().draft_watchlist, text)

    @app.post("/api/ai/suggest-selectors")
    def ai_suggest_selectors(url: str = Body(..., embed=True)):
        ai = require_ai()
        http = HttpClient(HttpSettings.from_settings(db.get_settings()))
        try:
            html = http.get(url).text
        except Exception as exc:
            raise HTTPException(502, f"could not fetch page: {exc}") from exc
        cleaned, truncated = _clean_html(html)
        return {**ai_call(ai.suggest_selectors, url, cleaned), "html_truncated": truncated}

    # ------------------------------------------------------------------- UI
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
