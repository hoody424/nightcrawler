# Changelog

## Unreleased

- Docker: `PUID` / `PGID` select the user the app runs as; `/data` ownership is fixed at start, so
  bind mounts owned by another user (Unraid appdata) work. `docker exec … claude` runs as that user too.
- Unraid Community Applications template.

## 1.0.0 - 2026-09-30

First public release.

- Web UI with dashboard, Geizhals-style faceted product search (live counts, price histogram,
  spec filters, flags), grid/list/spec-table views, comparison, price history, favourites and notes.
- Watchlists with per-list schedule, price range, keyword filters and notifications.
- Sources: eBay Browse API, Shopify stores, generic HTML (CSS selectors) with a live test preview.
- Automatic spec extraction (brand, category, storage, RAM, CPU, GPU, screen, …) and deal score vs. median.
- Sold/removed detection, price-drop tracking, retention.
- AI features via Claude subscription (Claude Code) or API key: relevance filter, spec extraction,
  natural-language search, watchlist drafting, deal check, selector detection.
- Notifications through Apprise (Discord, Telegram, ntfy, e-mail, Slack, …).
- Docker image with healthcheck, multi-arch builds, basic auth, YAML import/export, CSV/JSON export.
