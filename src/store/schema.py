"""SQLite schema v2 for multi-source properties."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_site TEXT NOT NULL,
        external_id TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT 'room',
        parent_property_id INTEGER,
        title TEXT,
        detail_url TEXT,
        prefecture_slug TEXT,
        prefecture_name TEXT,
        municipality TEXT,
        address TEXT,
        lat REAL,
        lng REAL,
        geocode_source TEXT,
        geocode_confidence REAL,
        layout TEXT,
        area_m2 REAL,
        area_m2_max REAL,
        built_year INTEGER,
        built_month INTEGER,
        construction_year_text TEXT,
        capacity_text TEXT,
        structure TEXT,
        floors_text TEXT,
        floor_number TEXT,
        point_text TEXT,
        availability_text TEXT,
        min_stay_days INTEGER,
        contract_fee_yen INTEGER,
        first_seen_at TEXT,
        last_seen_at TEXT,
        detail_scraped_at TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        catalog_rent_per_day_yen INTEGER,
        catalog_total_hint_yen INTEGER,
        total_score REAL DEFAULT 0.0,
        rent_score REAL DEFAULT 0.0,
        walk_score REAL DEFAULT 0.0,
        area_score REAL DEFAULT 0.0,
        age_score REAL DEFAULT 0.0,
        commute_score REAL DEFAULT 0.0,
        UNIQUE(source_site, external_id),
        FOREIGN KEY(parent_property_id) REFERENCES properties(id) ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS property_accesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        line_name TEXT,
        station_name TEXT,
        walk_minutes INTEGER,
        raw_text TEXT,
        sort_order INTEGER,
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS property_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        image_url TEXT NOT NULL,
        image_type TEXT,
        alt_text TEXT,
        sort_order INTEGER,
        scraped_at TEXT,
        UNIQUE(property_id, image_url),
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS property_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        link_type TEXT NOT NULL,
        url TEXT NOT NULL,
        label TEXT,
        scraped_at TEXT,
        UNIQUE(property_id, link_type, url),
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS property_features (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        feature_name TEXT NOT NULL,
        feature_category TEXT,
        raw_text TEXT,
        UNIQUE(property_id, feature_category, feature_name),
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS price_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        plan_key TEXT NOT NULL,
        plan_name TEXT,
        duration_min_days INTEGER NOT NULL DEFAULT 1,
        duration_max_days INTEGER,
        available INTEGER NOT NULL DEFAULT 1,
        presentation_unit TEXT NOT NULL DEFAULT 'per_day',
        rent_original_yen INTEGER,
        rent_current_yen INTEGER,
        management_yen INTEGER,
        utilities_yen INTEGER,
        utilities_included INTEGER NOT NULL DEFAULT 1,
        cleaning_yen INTEGER,
        campaign_label TEXT,
        raw_text TEXT,
        scraped_at TEXT,
        UNIQUE(property_id, plan_key),
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        campaign_type TEXT,
        title TEXT,
        content TEXT,
        target_period_text TEXT,
        target_condition_text TEXT,
        starts_on TEXT,
        ends_on TEXT,
        target_plan_key TEXT,
        discount_unit TEXT,
        discount_value INTEGER,
        discount_max_yen INTEGER,
        period_max_days INTEGER,
        stay_min_days INTEGER,
        stay_max_days INTEGER,
        contract_within_days INTEGER,
        package_rent_benefit_yen INTEGER,
        package_cleaning_benefit_yen INTEGER,
        package_fee_benefit_yen INTEGER,
        package_total_benefit_yen INTEGER,
        structure_source TEXT,
        parse_ok INTEGER DEFAULT 0,
        parse_warnings TEXT,
        raw_json TEXT,
        scraped_at TEXT,
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS property_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        scraped_at TEXT NOT NULL,
        is_active INTEGER,
        catalog_rent_per_day_yen INTEGER,
        min_discounted_monthly_total_yen INTEGER,
        raw_list_json TEXT,
        raw_detail_json TEXT,
        raw_html_path TEXT,
        parser_version TEXT,
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_site TEXT NOT NULL,
        url TEXT NOT NULL,
        page_type TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        status_code INTEGER,
        content_hash TEXT,
        storage_path TEXT,
        parser_version TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS shortlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL UNIQUE,
        status TEXT NOT NULL,
        comment TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_site TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL DEFAULT 'running',
        list_pages INTEGER DEFAULT 0,
        list_items INTEGER DEFAULT 0,
        detail_ok INTEGER DEFAULT 0,
        detail_fail INTEGER DEFAULT 0,
        error_summary TEXT,
        meta_json TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_run_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        source_site TEXT NOT NULL,
        target_key TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        status TEXT NOT NULL DEFAULT 'running',
        list_pages INTEGER DEFAULT 0,
        list_items INTEGER DEFAULT 0,
        detail_ok INTEGER DEFAULT 0,
        detail_fail INTEGER DEFAULT 0,
        error_summary TEXT,
        FOREIGN KEY(run_id) REFERENCES scrape_runs(id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_v2_properties_site_id ON properties(source_site, external_id);",
    "CREATE INDEX IF NOT EXISTS idx_v2_properties_prefecture ON properties(prefecture_name);",
    "CREATE INDEX IF NOT EXISTS idx_v2_properties_pref_slug ON properties(source_site, prefecture_slug);",
    "CREATE INDEX IF NOT EXISTS idx_v2_properties_active ON properties(is_active);",
    "CREATE INDEX IF NOT EXISTS idx_v2_properties_source ON properties(source_site);",
    "CREATE INDEX IF NOT EXISTS idx_v2_price_plans_prop ON price_plans(property_id);",
    "CREATE INDEX IF NOT EXISTS idx_v2_campaigns_prop ON campaigns(property_id);",
    "CREATE INDEX IF NOT EXISTS idx_v2_accesses_prop ON property_accesses(property_id);",
    "CREATE INDEX IF NOT EXISTS idx_v2_snapshots_prop ON property_snapshots(property_id);",
    "CREATE INDEX IF NOT EXISTS idx_v2_scrape_runs_source ON scrape_runs(source_site, started_at);",
    "CREATE INDEX IF NOT EXISTS idx_srt_source_target ON scrape_run_targets(source_site, target_key, finished_at);",
]


def init_schema(conn: sqlite3.Connection) -> None:
    """Create v2 tables if missing and record schema version."""
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()
    for stmt in DDL_STATEMENTS:
        cur.execute(stmt)
    cur.execute(
        """
        INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    try:
        return int(row[0] if not isinstance(row, sqlite3.Row) else row["value"])
    except (TypeError, ValueError):
        return None
