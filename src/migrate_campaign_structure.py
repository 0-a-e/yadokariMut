#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrate campaigns table: add structure columns and re-parse all rows.

Existing target_plan_code values from the old LLM path are overwritten by
mechanical rules (e.g. 早割 → all).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys

# Ensure src/ is on path when run as script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DB_PATH, ensure_campaigns_schema, get_db_connection
from campaign_classifier import run_classification

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def migrate(db_path: str | None = None, use_llm_residuals: bool = False) -> dict:
    target = db_path or DB_PATH
    os.environ["YADOKARIMUT_DB_PATH"] = target
    # Re-import path resolution if needed
    logger.info("Target DB: %s", target)

    if not os.path.exists(target):
        logger.warning("DB does not exist: %s", target)
        return {"status": "skipped"}

    backup = f"{target}.bak"
    shutil.copy2(target, backup)
    logger.info("Backup written to %s", backup)

    ensure_campaigns_schema()
    result = run_classification(
        use_llm_residuals=use_llm_residuals,
        force=True,
    )
    logger.info("Migration result: %s", result)
    return result


if __name__ == "__main__":
    migrate(use_llm_residuals=False)
