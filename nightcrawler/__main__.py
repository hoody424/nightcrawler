"""Command line entry point: python -m nightcrawler <command>."""

from __future__ import annotations

import argparse
import logging
import os
import sys

log = logging.getLogger("nightcrawler")

DEFAULT_DB = os.environ.get("NIGHTCRAWLER_DB", "/data/nightcrawler.db")
DEFAULT_CONFIG = os.environ.get("NIGHTCRAWLER_CONFIG", "/config/config.yaml")


def cmd_serve(args) -> int:
    import uvicorn

    from .app import create_app

    app = create_app(args.db, config_path=args.config, run_scheduler=not args.no_scheduler)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=args.access_log,
                proxy_headers=True, forwarded_allow_ips="*")
    return 0


def cmd_run(args) -> int:
    from .config import import_yaml
    from .crawler import Crawler
    from .db import Database

    db = Database(args.db)
    if db.is_empty() and os.path.exists(args.config):
        import_yaml(db, args.config)
    crawler = Crawler(db)
    rows = [r for r in db.list_searches() if r["enabled"] and (not args.search or r["name"] in args.search)]
    if not rows:
        log.error("no matching enabled watchlists")
        return 1
    failed = 0
    for row in rows:
        result = crawler.run_search(db.search_obj(row), trigger="cli")
        log.info("%s: %s fetched=%d matched=%d new=%d drops=%d", row["name"], result.status, result.fetched,
                 result.matched, len(result.new), len(result.price_drops))
        for err in result.errors:
            log.warning("  %s", err)
        failed += result.status == "error"
    return 1 if failed == len(rows) else 0


def cmd_import(args) -> int:
    from .config import import_yaml
    from .db import Database

    print(import_yaml(Database(args.db), args.file, overwrite=args.overwrite))
    return 0


def cmd_export_config(args) -> int:
    from .config import export_yaml
    from .db import Database

    sys.stdout.write(export_yaml(Database(args.db)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nightcrawler", description="Crawl for new and used products.")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database (default: {DEFAULT_DB})")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="YAML used to seed an empty database")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="web UI + API + scheduler (default)")
    p.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    p.add_argument("--no-scheduler", action="store_true", help="UI/API only, no background crawling")
    p.add_argument("--access-log", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("run", help="run watchlists once from the command line")
    p.add_argument("search", nargs="*", help="watchlist names (default: all enabled)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("import-config", help="import watchlists/sources/settings from YAML")
    p.add_argument("file")
    p.add_argument("--overwrite", action="store_true", help="replace entries with the same name")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("export-config", help="print watchlists/sources/settings as YAML")
    p.set_defaults(func=cmd_export_config)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    if args.command is None:
        args = parser.parse_args(["serve", *(argv or sys.argv[1:])])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
