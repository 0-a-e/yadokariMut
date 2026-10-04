import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import argparse


def cmd_db_init(args):
    """Initialize multi-source v2 SQLite schema."""
    from store.repository import Repository

    db_path = args.db or os.environ.get("YADOKARIMUT_V2_DB_PATH")
    repo = Repository(db_path)
    repo.init_db()
    print(f"v2 schema initialized: {repo.db_path}")


def cmd_scrape(args):
    """Multi-source v2 scrape (SourceAdapter + Repository)."""
    import json

    from ingest.pipeline import IngestPipeline
    from sources.registry import SourceRegistry
    from store.repository import Repository

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    source_id = args.source
    src_cfg = (config.get("sources") or {}).get(source_id) or {}
    if args.pref:
        src_cfg = {**src_cfg, "pref_filter": args.pref}
    if args.delay is not None:
        src_cfg = {**src_cfg, "delay_seconds": args.delay}

    db_path = args.db or os.environ.get("YADOKARIMUT_V2_DB_PATH")
    repo = Repository(db_path)
    repo.init_db()

    adapter = SourceRegistry.create(source_id, src_cfg)
    pipeline = IngestPipeline(adapter, repo, save_raw=not args.no_raw)

    if args.fixture_detail:
        with open(args.fixture_detail, "r", encoding="utf-8") as f:
            html = f.read()
        pid = pipeline.ingest_detail_html(
            html,
            detail_url=args.detail_url or "",
            external_id=args.external_id or "",
            prefecture_slug=(args.pref[0] if args.pref else None),
        )
        print(f"Upserted property id={pid} from fixture")
        return

    max_pages = None if args.all_pages else args.pages
    result = pipeline.run(
        max_pages=max_pages,
        list_only=args.list_only,
        max_details=args.max_details,
        mark_inactive=args.mark_inactive,
    )
    print(
        f"[{result.source_site}] list_pages={result.list_pages} "
        f"list_items={result.list_items} detail_ok={result.detail_ok} "
        f"detail_fail={result.detail_fail} errors={len(result.errors)}"
    )
    if result.errors:
        for e in result.errors[:10]:
            print(f"  - {e}", file=sys.stderr)


def cmd_export_map(args):

    """
    Exports search results to GeoJSON/KML.
    """
    from store.api_queries import export_geojson, export_kml

    params = {}
    if args.prefecture:
        params["prefecture_name"] = args.prefecture
    if args.max_rent:
        params["max_monthly_total_yen"] = args.max_rent
    if args.min_area:
        params["min_area_m2"] = args.min_area
    if args.features:
        params["required_features"] = args.features.split(",")

    if args.format == "geojson":
        res = export_geojson(params, args.out)
    else:
        res = export_kml(params, args.out)

    print(f"Export successful: {res['status']}")
    print(f"File saved to: {res['file_path']}")
    if "feature_count" in res:
        print(f"Features: {res['feature_count']}")
    if "placemark_count" in res:
        print(f"Placemarks: {res['placemark_count']}")


def cmd_geocode(args):
    """
    Geocodes v2 properties missing lat/lng coordinates in the database.
    """
    from store.geocode_v2 import geocode_missing_v2

    print("Running batch geocoding (v2)...")
    stats = geocode_missing_v2(
        limit=args.limit,
        provider=args.provider,
        force=args.force,
        retry_only=args.retry_only,
    )
    print(
        f"Processed: {stats.get('processed', 0)}, Success: {stats.get('success', 0)}, "
        f"Failed: {stats.get('failed', 0)}, Skipped: {stats.get('skipped', 0)}, "
        f"Unchanged: {stats.get('unchanged', 0)}, Remaining: {stats.get('remaining', 0)}"
    )
    if stats.get("skipped"):
        print(
            f"warn: {stats['skipped']} 件はプロバイダ障害等のため記録なしスキップ。"
            "時間を置いて再実行してください"
        )
    if stats.get("aborted"):
        print("warn: 連続プロバイダ障害のためサーキットブレーカにより打ち切りしました")


def main():
    parser = argparse.ArgumentParser(description="Yadokari Monthly Mansion Search System CLI")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # db-init
    parser_db = subparsers.add_parser("db-init", help="Initialize multi-source v2 SQLite schema")
    parser_db.add_argument("--db", type=str, help="Path to v2 DB (default YADOKARIMUT_V2_DB_PATH or yadokari_mut_v2.db)")

    # scrape
    parser_scrape = subparsers.add_parser("scrape", help="Multi-source v2 scrape via SourceAdapter")
    parser_scrape.add_argument("--source", type=str, default="unionmonthly", help="Source id (e.g. unionmonthly)")
    parser_scrape.add_argument("--pref", nargs="+", metavar="SLUG", help="Prefecture slug filter (e.g. tokyo)")
    parser_scrape.add_argument("--pages", type=int, default=1, help="Max list pages per pref (ignored with --all-pages)")
    parser_scrape.add_argument("--all-pages", action="store_true", help="Crawl all list pages")
    parser_scrape.add_argument("--list-only", action="store_true", help="Only collect list cards (no detail)")
    parser_scrape.add_argument("--max-details", type=int, help="Cap number of detail pages")
    parser_scrape.add_argument("--delay", type=float, help="Override delay_seconds")
    parser_scrape.add_argument("--mark-inactive", action="store_true", help="Deactivate IDs not seen in this run")
    parser_scrape.add_argument("--no-raw", action="store_true", help="Do not save raw HTML")
    parser_scrape.add_argument("--db", type=str, help="v2 DB path")
    parser_scrape.add_argument("--fixture-detail", type=str, help="Parse offline detail HTML fixture and upsert")
    parser_scrape.add_argument("--detail-url", type=str, help="Detail URL metadata for fixture")
    parser_scrape.add_argument("--external-id", type=str, help="External id override for fixture")

    # export-map
    parser_export = subparsers.add_parser("export-map", help="Export property search results to map format")
    parser_export.add_argument("--format", type=str, choices=["geojson", "kml"], default="geojson", help="Output map format")
    parser_export.add_argument("--out", type=str, help="Custom output file path")
    parser_export.add_argument("--prefecture", type=str, help="Prefecture name filter (e.g. '東京都')")
    parser_export.add_argument("--max-rent", type=int, help="Cheapest monthly total limit in yen")
    parser_export.add_argument("--min-area", type=float, help="Minimum floor area size in m2")
    parser_export.add_argument("--features", type=str, help="Comma-separated list of required features")

    # run-mcp
    subparsers.add_parser("run-mcp", help="Start the stdio MCP server")

    # geocode
    parser_geocode = subparsers.add_parser("geocode", help="Batch geocode v2 properties with missing coordinates")
    parser_geocode.add_argument("--limit", type=int, help="Limit number of properties to geocode in this batch")
    parser_geocode.add_argument("--force", action="store_true", help="Re-geocode all properties even if they already have coordinates")
    parser_geocode.add_argument("--provider", type=str, choices=["nominatim", "google"], help="Explicitly specify the geocoding provider")
    parser_geocode.add_argument("--retry-only", action="store_true", help="Retry only properties that already have a geocode_source (resolved or failed)")

    args = parser.parse_args()

    if args.command == "db-init":
        cmd_db_init(args)
    elif args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "export-map":
        cmd_export_map(args)
    elif args.command == "geocode":
        cmd_geocode(args)
    elif args.command == "run-mcp":
        from mcp_server import run_mcp_server

        run_mcp_server()

if __name__ == "__main__":
    main()
