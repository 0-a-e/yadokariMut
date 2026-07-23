import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.environ.get("YADOKARIMUT_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "yadokari_mut.db"))

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. properties table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_site TEXT NOT NULL,
        source_property_id TEXT NOT NULL,
        prefecture_slug TEXT,
        prefecture_name TEXT,
        municipality TEXT,
        title TEXT,
        detail_url TEXT,
        address TEXT,
        lat REAL,
        lng REAL,
        geocode_source TEXT,
        geocode_confidence REAL,
        layout TEXT,
        area_m2 REAL,
        construction_year_text TEXT,
        built_year INTEGER,
        built_month INTEGER,
        capacity_text TEXT,
        structure TEXT,
        floors_text TEXT,
        point_text TEXT,
        availability_text TEXT,
        first_seen_at TEXT,
        last_seen_at TEXT,
        detail_scraped_at TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        total_score REAL DEFAULT 0.0,
        rent_score REAL DEFAULT 0.0,
        walk_score REAL DEFAULT 0.0,
        area_score REAL DEFAULT 0.0,
        age_score REAL DEFAULT 0.0,
        commute_score REAL DEFAULT 0.0,
        UNIQUE(source_site, source_property_id)
    );
    """)

    # 2. property_accesses table
    cursor.execute("""
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
    """)

    # 3. property_images table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS property_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        image_url TEXT NOT NULL,
        image_type TEXT, -- thumbnail, floorplan, gallery, jsonld
        alt_text TEXT,
        sort_order INTEGER,
        scraped_at TEXT,
        UNIQUE(property_id, image_url),
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """)

    # 4. property_links table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS property_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        link_type TEXT NOT NULL, -- youtube, contact, map, option_guide, other
        url TEXT NOT NULL,
        label TEXT,
        scraped_at TEXT,
        UNIQUE(property_id, link_type, url),
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """)

    # 5. rent_plans table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rent_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        plan_code TEXT, -- s_short, short, middle, long
        plan_name TEXT,
        duration_text TEXT,
        available INTEGER,
        campaign_label TEXT,
        original_daily_rent_yen INTEGER,
        discounted_daily_rent_yen INTEGER,
        original_total_yen INTEGER,
        discounted_total_yen INTEGER,
        total_period_days INTEGER,
        management_fee_daily_yen INTEGER,
        cleaning_fee_yen INTEGER,
        raw_text TEXT,
        scraped_at TEXT,
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """)

    # 6. property_features table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS property_features (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        feature_name TEXT NOT NULL,
        feature_category TEXT, -- building, room, appliance, furniture, supplies, list_tag
        raw_text TEXT,
        UNIQUE(property_id, feature_category, feature_name),
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """)

    cursor.execute("""
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
        target_plan_code TEXT,
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
    """)

    # 8. property_snapshots table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS property_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        scraped_at TEXT NOT NULL,
        is_active INTEGER,
        min_discounted_daily_rent_yen INTEGER,
        min_discounted_monthly_total_yen INTEGER,
        raw_list_json TEXT,
        raw_detail_json TEXT,
        raw_html_path TEXT,
        parser_version TEXT,
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """)

    # 9. raw_pages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS raw_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_site TEXT NOT NULL,
        url TEXT NOT NULL,
        page_type TEXT NOT NULL, -- list, detail
        fetched_at TEXT NOT NULL,
        status_code INTEGER,
        content_hash TEXT,
        storage_path TEXT,
        parser_version TEXT
    );
    """)

    # 10. shortlists table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shortlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL UNIQUE,
        status TEXT NOT NULL, -- saved, hide, reject
        comment TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
    );
    """)

    # Create Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_properties_site_id ON properties(source_site, source_property_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_properties_prefecture ON properties(prefecture_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_properties_active ON properties(is_active);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rent_plans_prop_id ON rent_plans(property_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_property_features_prop_id ON property_features(property_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_property_accesses_prop_id ON property_accesses(property_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_property_snapshots_prop_id ON property_snapshots(property_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_prop_id ON campaigns(property_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_plan_code ON campaigns(target_plan_code);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_type ON campaigns(campaign_type);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_parse_ok ON campaigns(parse_ok);")

    ensure_campaigns_schema(conn)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")


# Columns added after initial schema for campaign structuring
CAMPAIGN_STRUCTURE_COLUMNS = {
    "target_plan_code": "TEXT",
    "discount_unit": "TEXT",
    "discount_value": "INTEGER",
    "discount_max_yen": "INTEGER",
    "period_max_days": "INTEGER",
    "stay_min_days": "INTEGER",
    "stay_max_days": "INTEGER",
    "contract_within_days": "INTEGER",
    "package_rent_benefit_yen": "INTEGER",
    "package_cleaning_benefit_yen": "INTEGER",
    "package_fee_benefit_yen": "INTEGER",
    "package_total_benefit_yen": "INTEGER",
    "structure_source": "TEXT",
    "parse_ok": "INTEGER DEFAULT 0",
    "parse_warnings": "TEXT",
}


def ensure_campaigns_schema(conn=None):
    """Add structured campaign columns if missing (safe for existing DBs)."""
    own_conn = False
    if conn is None:
        conn = get_db_connection()
        own_conn = True
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(campaigns)")
    existing = set()
    for row in cursor.fetchall():
        # Row factory may be sqlite3.Row or tuple
        name = row["name"] if isinstance(row, sqlite3.Row) else row[1]
        existing.add(name)

    for col, col_type in CAMPAIGN_STRUCTURE_COLUMNS.items():
        if col not in existing:
            cursor.execute(f"ALTER TABLE campaigns ADD COLUMN {col} {col_type}")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_prop_id ON campaigns(property_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_plan_code ON campaigns(target_plan_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_type ON campaigns(campaign_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_parse_ok ON campaigns(parse_ok)")
    conn.commit()
    if own_conn:
        conn.close()


if __name__ == "__main__":
    init_db()
