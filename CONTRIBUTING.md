# Contributing to nightcrawler

Thanks for helping! Bug reports, new source adapters, better attribute rules and UI polish are all welcome.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp config.example.yaml config.yaml
NIGHTCRAWLER_DB=./dev.db python -m nightcrawler --config config.yaml serve --port 8080
```

Open <http://localhost:8080>. The UI is plain ES modules in `nightcrawler/static/` - no build step, just reload.

## Before you open a pull request

```bash
ruff check nightcrawler tests
pytest
```

Tests never touch the network: parsers are tested against fixtures in `tests/fixtures/`, the AI backend
against a fake `claude` executable.

## Adding a source adapter

1. Create `nightcrawler/sources/<name>.py` with a `Source` subclass decorated with `@register("<name>")`.
2. Implement `search(self, search) -> Iterator[Product]`; fill as many `Product` fields as the site offers
   (shipping, seller rating, country, listing type…) - every field becomes a filter in the UI.
3. Describe the options in the class-level `fields` list; the web UI renders the form from it.
4. Import the module in `nightcrawler/sources/__init__.py` and add a fixture-based test.

Please prefer official APIs and public feeds, respect `robots.txt` and each site's terms of service.

## Improving attribute extraction

Rules live in `nightcrawler/attributes.py`. Add a title to the parametrised cases in
`tests/test_attributes.py` for every rule you change.
