# Security policy

Please report vulnerabilities **privately** via
[GitHub security advisories](https://github.com/hoody424/nightcrawler/security/advisories/new),
not as public issues. You'll get a reply within a few days.

## Deployment notes

- nightcrawler is designed for self-hosting on a private network. If you expose it, set
  `NIGHTCRAWLER_USERNAME` / `NIGHTCRAWLER_PASSWORD` (HTTP basic auth) and put it behind HTTPS
  (e.g. Caddy, Traefik or nginx).
- Secrets: prefer environment variables (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, eBay keys).
  A subscription token entered in the UI is stored in the SQLite database in the `/data` volume;
  it is never returned by the API and never included in config exports.
- Scraped content (titles, descriptions, images) is untrusted and is always HTML-escaped in the UI.
