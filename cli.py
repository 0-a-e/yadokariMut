import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import json
import argparse
from database import init_db
from scraper import upsert_normalized_property, scrape_list_pages, scrape_detail_pages
from parser import normalize_property
from anomaly_detector import detect_anomalies
from commute_scorer import update_all_scores
from mcp_server import run_mcp_server
from services import db_export_geojson, db_export_kml

def cmd_import_json(args):
    """
    Imports list page JSON output (like properties.json or test_properties.json) into the SQLite DB.
    """
    print(f"Importing JSON data from {args.file}...")
    if not os.path.exists(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)
        
    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Loaded {len(data)} properties. Inserting into database...")
    
    success_count = 0
    for idx, item in enumerate(data):
        try:
            # Prepare empty detail data since we are importing from a list-only JSON
            detail_data = {
                "json_ld": {},
                "specs": {},
                "rent_plans": [],
                "campaigns": [],
                "youtube_links": [],
                "images": []
            }
            # Extract coordinates if present in import format (though raw properties.json doesn't have it)
            if "lat" in item and "lng" in item:
                detail_data["json_ld"] = {"geo": {"latitude": item["lat"], "longitude": item["lng"]}}
                
            # If the item has access list but no accesses in specs, add specs access
            if "access" in item:
                detail_data["specs"]["交通"] = item["access"]
                
            if "features" in item:
                detail_data["specs"]["基本設備"] = {"list_tag": item["features"]}
                
            # If construction year is present
            if "construction_year" in item:
                detail_data["specs"]["築年数"] = item["construction_year"]
                
            normalized = normalize_property(item, detail_data)
            
            # Apply details fetched date if it's already got detail properties (like if it has images/details in import format)
            if "detail_scraped_at" in item:
                normalized["detail_scraped_at"] = item["detail_scraped_at"]
                
            upsert_normalized_property(normalized, raw_list_json=item)
            success_count += 1
        except Exception as e:
            print(f"Error importing item {idx} ({item.get('title')}): {e}", file=sys.stderr)
            
    print(f"Successfully imported {success_count}/{len(data)} properties.")
    
    # Automatically geocode missing coordinates
    print("Geocoding imported properties with missing coordinates...")
    from geocoder import geocode_missing_properties
    geocode_missing_properties()

def cmd_scrape(args):
    """
    Scrapes list pages and then detailed pages for properties.
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        print("Error: config.json not found.", file=sys.stderr)
        sys.exit(1)
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    configured_prefectures = config["sources"]["bratto"]["prefectures"]
    if args.all_prefectures:
        prefectures = list(configured_prefectures.keys())
    elif args.prefecture:
        prefectures = args.prefecture
    else:
        print("No prefecture specified. Use --prefecture PREFECTURE [PREFECTURE ...] or --all-prefectures.")
        return

    unknown_prefectures = [pref for pref in prefectures if pref not in configured_prefectures]
    if unknown_prefectures:
        print(
            f"Error: unknown prefecture slug(s): {', '.join(unknown_prefectures)}",
            file=sys.stderr,
        )
        print(
            "Available prefectures: " + ", ".join(configured_prefectures.keys()),
            file=sys.stderr,
        )
        sys.exit(1)
    
    all_crawled = []
    max_pages = 999999 if getattr(args, "all", False) else args.pages
    for pref in prefectures:
        try:
            crawled = scrape_list_pages(pref, config, max_pages=max_pages, delay=args.delay)
            all_crawled.extend(crawled)
        except Exception as e:
            print(f"Error scraping prefecture '{pref}': {e}", file=sys.stderr)
            
    if all_crawled:
        print(f"Starting detail scrape for {len(all_crawled)} properties...")
        scrape_detail_pages(all_crawled, delay=args.delay)
        print("Scrape completed successfully.")
        
        # Automatically geocode missing coordinates
        print("Geocoding properties with missing coordinates...")
        from geocoder import geocode_missing_properties
        geocode_missing_properties()
        
        # Automatically recalculate scores
        print("Recalculating scores...")
        update_all_scores()
        
        # Auto-classify campaigns and features if requested
        if getattr(args, "classify", False):
            print("Automatically classifying campaigns...")
            from campaign_classifier import run_classification
            run_classification(use_batch=False)
            
            print("Automatically classifying property features...")
            from feature_classifier import run_feature_classification
            run_feature_classification(use_batch=False)
    else:
        print("No properties found to scrape details.")

def cmd_detect_anomalies(args):
    """
    Runs anomaly detector and prints out details.
    """
    print("Running anomaly detection...")
    anomalies = detect_anomalies()
    if not anomalies:
        print("No anomalies found in database. Clean data!")
        return
        
    print(f"Found anomalies in {len(anomalies)} properties:")
    for p_id, info in anomalies.items():
        print(f"\nProperty ID {p_id} (Title: {info['title']})")
        print(f"  URL: {info['detail_url']}")
        for anom in info["anomalies"]:
            print(f"  - [{anom['type']}] {anom['message']}")

def cmd_score(args):
    """
    Calculates and updates scores for all properties.
    """
    print("Recalculating and updating scores for all properties...")
    update_all_scores()

def cmd_classify_campaigns(args):
    """
    Classifies scraped campaigns to their corresponding rent plans.
    """
    from campaign_classifier import run_classification
    print("Running campaign classification...")
    use_batch = not args.realtime
    res = run_classification(use_batch=use_batch)
    print(f"Classification completed: {res['status']}")
    print(f"Mechanical updates: {res['mechanical_count']}")
    print(f"LLM updates: {res['llm_count']}")
    print(f"Total campaigns updated: {res['total_count']}")

def cmd_classify_features(args):
    """
    Classifies scraped property features to standardized master names.
    """
    from feature_classifier import run_feature_classification
    print("Running property features classification...")
    use_batch = not args.realtime
    res = run_feature_classification(use_batch=use_batch)
    print(f"Classification completed: {res['status']}")
    print(f"Mechanical updates: {res['mechanical_count']}")
    print(f"LLM updates: {res['llm_count']}")
    print(f"Total feature records updated: {res['total_count']}")

def cmd_db_init_v2(args):
    """Initialize multi-source v2 SQLite schema."""
    from store.repository import Repository

    db_path = args.db or os.environ.get("YADOKARIMUT_V2_DB_PATH")
    repo = Repository(db_path)
    repo.init_db()
    print(f"v2 schema initialized: {repo.db_path}")


def cmd_scrape_v2(args):
    """Multi-source v2 scrape (SourceAdapter + Repository)."""
    import sources  # noqa: F401 — register adapters
    from ingest.pipeline import IngestPipeline
    from sources.registry import SourceRegistry
    from store.repository import Repository

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
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
    params = {}
    if args.prefecture:
        params["prefecture_name"] = args.prefecture
    if args.max_rent:
        params["max_monthly_total_yen"] = args.max_rent
    if args.plan:
        params["plan_code"] = args.plan
    if args.min_area:
        params["min_area_m2"] = args.min_area
    if args.features:
        params["required_features"] = args.features.split(",")
        
    if args.format == "geojson":
        res = db_export_geojson(params, args.out)
    else:
        res = db_export_kml(params, args.out)
        
    print(f"Export successful: {res['status']}")
    print(f"File saved to: {res['file_path']}")
    if "feature_count" in res:
        print(f"Features: {res['feature_count']}")
    if "placemark_count" in res:
        print(f"Placemarks: {res['placemark_count']}")

def cmd_geocode(args):
    """
    Geocodes properties missing lat/lng coordinates in the database.
    """
    print("Running batch geocoding...")
    from geocoder import geocode_missing_properties
    geocode_missing_properties(
        limit=args.limit,
        force=args.force,
        provider=args.provider,
        retry_only=args.retry_only,
        filter_expr=args.filter
    )

def main():
    parser = argparse.ArgumentParser(description="Yadokari Monthly Mansion Search System CLI")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")
    
    # db-init
    subparsers.add_parser("db-init", help="Initialize SQLite database schema (v1 / bratto)")

    # db-init-v2
    parser_db_v2 = subparsers.add_parser("db-init-v2", help="Initialize multi-source v2 SQLite schema")
    parser_db_v2.add_argument("--db", type=str, help="Path to v2 DB (default YADOKARIMUT_V2_DB_PATH or yadokari_mut_v2.db)")
    
    # import-json
    parser_import = subparsers.add_parser("import-json", help="Import list properties JSON file to DB")
    parser_import.add_argument("file", type=str, help="Path to JSON file (e.g. test_properties.json)")
    
    # scrape
    parser_scrape = subparsers.add_parser("scrape", help="Run online scraping for list and details (v1 bratto)")

    # scrape-v2
    parser_sv2 = subparsers.add_parser("scrape-v2", help="Multi-source v2 scrape via SourceAdapter")
    parser_sv2.add_argument("--source", type=str, default="unionmonthly", help="Source id (e.g. unionmonthly)")
    parser_sv2.add_argument("--pref", nargs="+", metavar="SLUG", help="Prefecture slug filter (e.g. tokyo)")
    parser_sv2.add_argument("--pages", type=int, default=1, help="Max list pages per pref (ignored with --all-pages)")
    parser_sv2.add_argument("--all-pages", action="store_true", help="Crawl all list pages")
    parser_sv2.add_argument("--list-only", action="store_true", help="Only collect list cards (no detail)")
    parser_sv2.add_argument("--max-details", type=int, help="Cap number of detail pages")
    parser_sv2.add_argument("--delay", type=float, help="Override delay_seconds")
    parser_sv2.add_argument("--mark-inactive", action="store_true", help="Deactivate IDs not seen in this run")
    parser_sv2.add_argument("--no-raw", action="store_true", help="Do not save raw HTML")
    parser_sv2.add_argument("--db", type=str, help="v2 DB path")
    parser_sv2.add_argument("--fixture-detail", type=str, help="Parse offline detail HTML fixture and upsert")
    parser_sv2.add_argument("--detail-url", type=str, help="Detail URL metadata for fixture")
    parser_sv2.add_argument("--external-id", type=str, help="External id override for fixture")

    prefecture_group = parser_scrape.add_mutually_exclusive_group()
    prefecture_group.add_argument(
        "--prefecture",
        nargs="+",
        metavar="PREFECTURE",
        help="Prefecture slug(s) to scrape (e.g. tokyo osaka)",
    )
    prefecture_group.add_argument(
        "--all-prefectures",
        action="store_true",
        help="Scrape every prefecture configured in config.json",
    )
    parser_scrape.add_argument("--pages", type=int, default=5, help="Number of list pages to crawl")
    parser_scrape.add_argument("--all", action="store_true", help="Scrape all available pages until the end")
    parser_scrape.add_argument("--delay", type=float, default=1.5, help="Delay between requests in seconds")
    parser_scrape.add_argument("--classify", action="store_true", help="Automatically classify campaigns to rent plans after scraping")
    
    # detect-anomalies
    subparsers.add_parser("detect-anomalies", help="Run anomaly detection on database")
    
    # score
    subparsers.add_parser("score", help="Recalculate scores for all properties")
    
    # export-map
    parser_export = subparsers.add_parser("export-map", help="Export property search results to map format")
    parser_export.add_argument("--format", type=str, choices=["geojson", "kml"], default="geojson", help="Output map format")
    parser_export.add_argument("--out", type=str, help="Custom output file path")
    parser_export.add_argument("--prefecture", type=str, help="Prefecture name filter (e.g. '東京都')")
    parser_export.add_argument("--max-rent", type=int, help="Cheapest monthly total limit in yen")
    parser_export.add_argument("--plan", type=str, help="Rent plan code filter")
    parser_export.add_argument("--min-area", type=float, help="Minimum floor area size in m2")
    parser_export.add_argument("--features", type=str, help="Comma-separated list of required features")
    
    # run-mcp
    subparsers.add_parser("run-mcp", help="Start the stdio MCP server")
    
    # geocode
    parser_geocode = subparsers.add_parser("geocode", help="Batch geocode properties with missing coordinates")
    parser_geocode.add_argument("--limit", type=int, help="Limit number of properties to geocode in this batch")
    parser_geocode.add_argument("--force", action="store_true", help="Re-geocode all properties even if they already have coordinates")
    parser_geocode.add_argument("--provider", type=str, choices=["nominatim", "google"], help="Explicitly specify the geocoding provider")
    parser_geocode.add_argument("--retry-only", action="store_true", help="Retry only properties geocoded or failed by the specified provider(s)")
    parser_geocode.add_argument("--filter", type=str, help="Logical filter expression to select target properties (e.g. 'failed:nominatim AND NOT failed:google')")
    
    # classify-campaigns
    parser_classify = subparsers.add_parser("classify-campaigns", help="Classify campaigns to rent plans using mechanical & LLM match")
    parser_classify.add_argument("--realtime", action="store_true", help="Use real-time API concurrently instead of Batch API")
    
    # classify-features
    parser_classify_features = subparsers.add_parser("classify-features", help="Classify property features to standardized master names using mechanical & LLM match")
    parser_classify_features.add_argument("--realtime", action="store_true", help="Use real-time API concurrently instead of Batch API")
    
    args = parser.parse_args()
    
    if args.command == "db-init":
        init_db()
    elif args.command == "db-init-v2":
        cmd_db_init_v2(args)
    elif args.command == "import-json":
        cmd_import_json(args)
    elif args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "scrape-v2":
        cmd_scrape_v2(args)

    elif args.command == "detect-anomalies":
        cmd_detect_anomalies(args)
    elif args.command == "score":
        cmd_score(args)
    elif args.command == "export-map":
        cmd_export_map(args)
    elif args.command == "classify-campaigns":
        cmd_classify_campaigns(args)
    elif args.command == "classify-features":
        cmd_classify_features(args)
    elif args.command == "geocode":
        cmd_geocode(args)
    elif args.command == "run-mcp":
        run_mcp_server()

if __name__ == "__main__":
    main()
