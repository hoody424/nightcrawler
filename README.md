<div align="center">

# 🕷 nightcrawler

**Self-hosted crawler for new & used products — with Geizhals-style filters and Claude-powered AI.**

Watch marketplaces and shops for the things you want, filter listings by real specs,
get alerted on new finds and price drops, and let Claude weed out junk and judge deals.

[![CI](https://github.com/hoody424/nightcrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/hoody424/nightcrawler/actions/workflows/ci.yml)
[![Docker image](https://img.shields.io/badge/docker-ghcr.io%2Fhoody424%2Fnightcrawler-2496ED?logo=docker&logoColor=white)](https://github.com/hoody424/nightcrawler/pkgs/container/nightcrawler)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)

<img src="docs/screenshots/products.png" alt="Faceted product search" width="900">

</div>

---

## Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Quick start](#quick-start-docker)
- [AI with your Claude subscription](#ai-with-your-claude-subscription)
- [Sources](#sources)
- [Filters](#filters--how-they-work)
- [Notifications](#notifications)
- [Configuration](#configuration)
- [CLI & API](#cli--api)
- [How it works](#how-it-works)
- [Development](#development)
- [Responsible use](#responsible-use)

## Features

**Find**
- **Watchlists** — query, conditions (new / used / refurbished), price range, must-have and excluded words, sources and schedule per list.
- **Sources** — official **eBay Browse API**, any **Shopify** store, and a **generic web-page adapter** driven by CSS selectors (with live test preview and ✨ AI selector detection). Pluggable — [add your own](CONTRIBUTING.md#adding-a-source-adapter).
- **Polite crawling** — per-host rate limit, retries with back-off, `robots.txt` respected by default.

**Filter like Geizhals**
- **Faceted search with live counts** — every option shows how many listings you'd get; values within a group are OR-ed, groups are AND-ed.
- **Real specs from messy titles** — brand, category, model, storage, RAM, CPU, GPU, VRAM, screen size, resolution, refresh rate, megapixels, colour, year — extracted automatically (EN + DE), optionally refined by AI.
- **Listing details** — original box, warranty, invoice, defective ("keine Garantie" is understood as *no* warranty).
- **Price histogram & slider**, price incl. shipping, free shipping, offer type (buy now / auction / negotiable "VB"), seller rating, item location.
- **Deal score** — how far a listing is below the median of comparable listings.
- Grid, list and **spec-table** views, **side-by-side comparison**, shareable filter URLs, CSV/JSON export.

**Track**
- **Price history** per listing and price-drop detection.
- **Sold / removed detection** — listings that disappear are marked, not silently deleted.
- Favourites, notes, hide; dashboard with trends.
- **Notifications** to Discord, Telegram, ntfy, e-mail, Slack, Gotify, Pushover … via [Apprise](https://github.com/caronc/apprise).

**✨ AI (optional) — works with your Claude Pro/Max subscription**
- **Relevance filter** per watchlist in plain language: *"only complete consoles, no games or accessories"*.
- **Natural-language search** → filters: *"used ThinkPad with 16GB under 400 €, not defective"*.
- **Describe a watchlist** and let Claude fill in query, keywords and rules.
- **Deal check** per listing: verdict, fair price, red flags, questions to ask the seller.
- **Selector detection** for new shops.

## Screenshots

| | |
|---|---|
| **Dashboard**<br><img src="docs/screenshots/dashboard.png" width="440"> | **Filters in action**<br><img src="docs/screenshots/products-filtered.png" width="440"> |
| **Listing details & price history**<br><img src="docs/screenshots/product-drawer.png" width="440"> | **Side-by-side comparison**<br><img src="docs/screenshots/compare.png" width="440"> |
| **Spec table**<br><img src="docs/screenshots/products-table.png" width="440"> | **Source editor with live test**<br><img src="docs/screenshots/source-test.png" width="440"> |
| **Watchlists**<br><img src="docs/screenshots/watchlists.png" width="440"> | **Dark mode**<br><img src="docs/screenshots/products-dark.png" width="440"> |

<p align="center"><img src="docs/screenshots/mobile.png" width="220" alt="Mobile">&nbsp;&nbsp;<img src="docs/screenshots/mobile-filters.png" width="220" alt="Mobile filters"></p>

> The screenshots show the built-in demo source, which crawls [webscraper.io's public test shop](https://webscraper.io/test-sites/e-commerce/static) — so a fresh install has real data to play with.

## Quick start (Docker)

```bash
git clone https://github.com/hoody424/nightcrawler.git
cd nightcrawler
cp .env.example .env        # optional: Claude token, eBay keys, basic auth
docker compose up -d
```

Open **http://localhost:8080**. The first start seeds the demo source and a few watchlists; the first crawl begins within seconds.

Using the pre-built image instead (amd64 + arm64, e.g. Raspberry Pi / NAS):

```bash
docker run -d --name nightcrawler -p 8080:8080 -v nightcrawler-data:/data \
  --env-file .env ghcr.io/hoody424/nightcrawler:latest
```

All state (database, settings, Claude login) lives in the `/data` volume — back it up, and updates are just `docker compose pull && docker compose up -d`.

## AI with your Claude subscription

nightcrawler talks to Claude through the official **Claude Code CLI**, which is bundled in the image. That lets it use your **Claude Pro or Max subscription** — no API billing.

1. Create a long-lived token (opens a browser login to your Claude account):
   ```bash
   docker compose exec -it nightcrawler claude setup-token
   ```
   (or run `claude setup-token` on any machine that has Claude Code).
2. Put the printed `sk-ant-oat…` token into `.env` as `CLAUDE_CODE_OAUTH_TOKEN=…` and `docker compose up -d` — **or** paste it in the UI under **Settings → AI**.
3. Click **Test connection**. The sidebar now shows *✨ AI: Claude subscription*.

Alternatively log in once inside the container — the login is kept in the `/data` volume:
`docker compose exec -it nightcrawler claude auth login`

Notes
- AI calls count towards your plan's usage limits. One call analyses up to 25 listings; the **Max AI calls / hour** setting (default 60) keeps things in check.
- Only *new* listings of watchlists that have an AI rule are sent to Claude — unless you enable *Extract specs with AI for every new listing*.
- A subscription is meant for **your own** use. If you run nightcrawler for other people, use an Anthropic API key instead: set `ANTHROPIC_API_KEY` and choose the *Anthropic API key* backend.
- No AI configured? Everything else works; the AI buttons are simply disabled.

## Sources

| Type | What it's for | Setup |
|---|---|---|
| `ebay` | eBay via the official Browse API — condition, shipping, seller rating, auctions, item location | Create a free Production keyset at [developer.ebay.com](https://developer.ebay.com/my/keys), set `EBAY_ENABLED=true`, `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`. Pick the marketplace (EBAY_DE, EBAY_US, …) in the UI. |
| `shopify` | Any Shopify-based shop (many refurb / second-hand resellers) via its public `products.json` | Just the store URL and a default condition. |
| `html` | Any other shop or classifieds site | Search URL with `{query}` / `{page}` placeholders + CSS selectors. Use **Run test** to see what gets parsed and which specs are extracted, or **✨ Detect selectors** to let Claude propose them. |

Secrets in source options can be written as `${ENV_VAR}` — they're resolved at runtime and never stored in the database.

## Filters — how they work

- **Disjunctive facets.** Counts in a group ignore that group's own selection, so after ticking *Lenovo* you still see how many *Asus* listings there are — exactly like Geizhals. All other active filters apply.
- **Numeric specs** (storage, RAM, screen, …) can be ticked as values or constrained with a min/max range.
- **Flags** (original box, warranty, invoice, defective) are tri-state: *any*, *yes*, *no*.
- **Deal score** = how far the price is below the median of active listings of the same watchlist and condition (needs ≥ 3 comparable listings).
- **Sold/removed**: a listing that isn't returned for *N* runs (default 2) moves to *Sold/removed*.
- Every filter state is in the URL — bookmark it or share it. **＋ Watchlist** turns the current search into a watchlist.

## Notifications

Add one [Apprise URL](https://github.com/caronc/apprise/wiki) per line under **Settings → Notifications**, e.g.

```text
discord://webhook_id/webhook_token
tgram://bot_token/chat_id
ntfy://my-secret-topic
mailtos://user:app-password@gmail.com
```

You'll get one message per watchlist run with new listings and price drops (configurable threshold, optionally only listings ≥ X % below median). **Send test notification** checks the setup.

## Configuration

Environment variables (all optional):

| Variable | Purpose |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude subscription token from `claude setup-token` |
| `ANTHROPIC_API_KEY` | Alternative: Anthropic API key (billed per token) |
| `EBAY_ENABLED`, `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` | eBay Browse API |
| `NIGHTCRAWLER_USERNAME`, `NIGHTCRAWLER_PASSWORD` | Protect the UI/API with HTTP basic auth |
| `NIGHTCRAWLER_DB` | Database path (default `/data/nightcrawler.db`) |
| `NIGHTCRAWLER_CONFIG` | Seed YAML used when the database is empty (default `/config/config.yaml`) |
| `PORT` | Web port (default `8080`) |

Everything else — watchlists, sources, notification targets, crawl politeness, retention, AI model/effort/limits — is managed in the web UI and stored in SQLite. **Settings → Data** exports/imports it as YAML (see [`config.example.yaml`](config.example.yaml)); secrets are never exported.

## CLI & API

```bash
python -m nightcrawler serve                  # web UI + API + scheduler (default)
python -m nightcrawler run                    # run all enabled watchlists once
python -m nightcrawler run "Demo · laptops"   # run specific watchlists
python -m nightcrawler import-config my.yaml  # import watchlists/sources/settings
python -m nightcrawler export-config > backup.yaml
```

In Docker: `docker compose exec nightcrawler python -m nightcrawler run`.

The REST API is documented interactively at **`/api/docs`**. Example — the same faceted search the UI uses:

```bash
curl -s localhost:8080/api/products/search -H 'content-type: application/json' -d '{
  "conditions": ["used", "refurbished"], "price_max": 400,
  "attrs": {"ram_gb": ["16", "32"]}, "flags": {"defective": "exclude"}, "sort": "deal"
}'
```

## How it works

```mermaid
flowchart LR
    subgraph Container
      S[Scheduler] -->|due watchlists| C[Crawler]
      C --> A1[eBay API]
      C --> A2[Shopify feed]
      C --> A3[HTML + CSS selectors]
      C -->|match & store| DB[(SQLite)]
      C -->|new listings| AI[✨ Claude<br>Claude Code CLI / API]
      AI -->|relevance + specs| DB
      C --> N[Apprise notifications]
      W[FastAPI + web UI] --> DB
      W -->|NL search, deal check| AI
    end
    U((You)) --> W
```

- Python 3.11+, FastAPI, SQLite (WAL), BeautifulSoup; the UI is dependency-free ES modules — no build step.
- One process runs the web server and the scheduler; data lives in one SQLite file.
- Spec extraction is rule-based ([`attributes.py`](nightcrawler/attributes.py)); source-provided data and AI results take precedence.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
NIGHTCRAWLER_DB=./dev.db python -m nightcrawler --config config.example.yaml serve --port 8080
ruff check nightcrawler tests && pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) — new source adapters and extraction rules are very welcome.

## Responsible use

nightcrawler is meant for personal deal hunting. Prefer official APIs and public feeds, keep request rates low, respect `robots.txt` and each site's terms of service, and don't republish scraped data. See [SECURITY.md](SECURITY.md) for deployment advice.

## License

[GPL-3.0](LICENSE) © hoody424 and contributors.
