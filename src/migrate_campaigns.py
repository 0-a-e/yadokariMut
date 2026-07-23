#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migration script to update campaigns table schema and add indexes.

Creates a backup of the database before making any modifications.
"""

import os
import shutil
import sqlite3
import logging
from database import DB_PATH, get_db_connection, init_db

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def migrate():
    logger.info(f"Target database path: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        logger.warning("Database file does not exist yet. Initializing a new database...")
        init_db()
        logger.info("Database initialized successfully.")
        return

    # 1. Create a backup
    backup_path = f"{DB_PATH}.bak"
    try:
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"Created database backup at: {backup_path}")
    except Exception as e:
        logger.error(f"Failed to create database backup: {e}")
        raise

    # 2. Modify campaigns table schema if needed
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check existing columns
        cursor.execute("PRAGMA table_info(campaigns)")
        columns = [row["name"] for row in cursor.fetchall()]
        
        if "target_plan_code" not in columns:
            logger.info("Adding 'target_plan_code' column to 'campaigns' table...")
            cursor.execute("ALTER TABLE campaigns ADD COLUMN target_plan_code TEXT")
            conn.commit()
            logger.info("'target_plan_code' column added successfully.")
        else:
            logger.info("'target_plan_code' column already exists.")

        # Create indexes
        logger.info("Creating indexes on 'campaigns' table...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_prop_id ON campaigns(property_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_plan_code ON campaigns(target_plan_code)")
        conn.commit()
        logger.info("Indexes created successfully.")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()
        # Restore backup
        logger.info(f"Restoring database backup from {backup_path}...")
        conn.close()
        shutil.copy2(backup_path, DB_PATH)
        logger.info("Database restored to pre-migration state.")
        raise
    finally:
        if conn:
            conn.close()

    # 3. Initialize/validate database structures via init_db
    logger.info("Validating database initialization...")
    init_db()
    logger.info("Migration completed successfully.")

if __name__ == "__main__":
    migrate()
