#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Campaign classification / structuring.

Primary path is mechanical (type rules + regex + optional cam_* JS).
LLM is optional and only used for residual rows where parse_ok=0.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from database import get_db_connection, ensure_campaigns_schema
from campaign_structurer import structure_campaign, extract_cam_js_objects
from llm_client import DeepSeekClient, DeepSeekBatchClient, DEEPSEEK_API_KEY

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STRUCTURE_COLUMNS = [
    "target_plan_code",
    "discount_unit",
    "discount_value",
    "discount_max_yen",
    "period_max_days",
    "stay_min_days",
    "stay_max_days",
    "contract_within_days",
    "package_rent_benefit_yen",
    "package_cleaning_benefit_yen",
    "package_fee_benefit_yen",
    "package_total_benefit_yen",
    "structure_source",
    "parse_ok",
    "parse_warnings",
    "starts_on",
    "ends_on",
]

SYSTEM_PROMPT = (
    "You are a helpful assistant specialized in structuring Japanese monthly-apartment campaigns. "
    "Respond with a single JSON object only (no markdown) using these keys:\n"
    "target_plan_code: one of s_short, short, middle, long, all, UNKNOWN\n"
    "discount_unit: one of yen, percent, package, pokkiri, free_first_week, unknown\n"
    "discount_value: number or null (yen/day, percent, or monthly fixed yen)\n"
    "discount_max_yen: number or null\n"
    "period_max_days: number or null\n"
    "stay_min_days: number or null\n"
    "stay_max_days: number or null\n"
)

USER_PROMPT_TEMPLATE = (
    "Campaign type: {campaign_type}\n"
    "Title: {title}\n"
    "Content: {content}\n"
    "Period: {period}\n"
    "Condition: {condition}\n"
)


def ensure_schema():
    ensure_campaigns_schema()


def _apply_structure_to_row(cursor, campaign_id: int, structured: dict):
    cursor.execute(
        """
        UPDATE campaigns SET
            target_plan_code = ?,
            discount_unit = ?,
            discount_value = ?,
            discount_max_yen = ?,
            period_max_days = ?,
            stay_min_days = ?,
            stay_max_days = ?,
            contract_within_days = ?,
            package_rent_benefit_yen = ?,
            package_cleaning_benefit_yen = ?,
            package_fee_benefit_yen = ?,
            package_total_benefit_yen = ?,
            structure_source = ?,
            parse_ok = ?,
            parse_warnings = ?,
            starts_on = COALESCE(?, starts_on),
            ends_on = COALESCE(?, ends_on)
        WHERE id = ?
        """,
        (
            structured.get("target_plan_code"),
            structured.get("discount_unit"),
            structured.get("discount_value"),
            structured.get("discount_max_yen"),
            structured.get("period_max_days"),
            structured.get("stay_min_days"),
            structured.get("stay_max_days"),
            structured.get("contract_within_days"),
            structured.get("package_rent_benefit_yen"),
            structured.get("package_cleaning_benefit_yen"),
            structured.get("package_fee_benefit_yen"),
            structured.get("package_total_benefit_yen"),
            structured.get("structure_source"),
            structured.get("parse_ok") or 0,
            structured.get("parse_warnings_json")
            or json.dumps(structured.get("parse_warnings") or [], ensure_ascii=False),
            structured.get("starts_on"),
            structured.get("ends_on"),
            campaign_id,
        ),
    )


def _load_cam_js_for_property(cursor, property_id: int) -> list:
    """Best-effort: load cam_* from latest snapshot HTML path."""
    cursor.execute(
        """
        SELECT raw_html_path FROM property_snapshots
        WHERE property_id = ? AND raw_html_path IS NOT NULL
        ORDER BY scraped_at DESC LIMIT 1
        """,
        (property_id,),
    )
    row = cursor.fetchone()
    if not row:
        return []
    path = row["raw_html_path"] if hasattr(row, "keys") else row[0]
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return extract_cam_js_objects(f.read())
    except OSError as e:
        logger.debug("Could not read HTML for property %s: %s", property_id, e)
        return []


def classify_mechanically(force: bool = True) -> dict:
    """Structure all campaigns (or only parse_ok=0 if force=False) mechanically.

    Returns stats dict.
    """
    ensure_schema()
    conn = get_db_connection()
    cursor = conn.cursor()

    if force:
        cursor.execute(
            """
            SELECT id, property_id, campaign_type, title, content,
                   target_period_text, target_condition_text, starts_on, ends_on, raw_json
            FROM campaigns
            """
        )
    else:
        cursor.execute(
            """
            SELECT id, property_id, campaign_type, title, content,
                   target_period_text, target_condition_text, starts_on, ends_on, raw_json
            FROM campaigns
            WHERE parse_ok IS NULL OR parse_ok = 0
               OR target_plan_code IS NULL
               OR structure_source IS NULL
            """
        )
    rows = cursor.fetchall()

    cam_js_cache: dict[int, list] = {}
    ok = 0
    fail = 0
    cam_js_hits = 0

    for row in rows:
        pid = row["property_id"]
        if pid not in cam_js_cache:
            cam_js_cache[pid] = _load_cam_js_for_property(cursor, pid)
        cam_objects = cam_js_cache[pid]
        if cam_objects:
            cam_js_hits += 1

        structured = structure_campaign(
            campaign_type=row["campaign_type"],
            title=row["title"],
            content=row["content"],
            period_text=row["target_period_text"],
            condition_text=row["target_condition_text"],
            cam_objects=cam_objects,
            starts_on=row["starts_on"],
            ends_on=row["ends_on"],
        )
        _apply_structure_to_row(cursor, row["id"], structured)
        if structured.get("parse_ok"):
            ok += 1
        else:
            fail += 1

    conn.commit()
    conn.close()
    stats = {
        "processed": len(rows),
        "parse_ok": ok,
        "parse_fail": fail,
        "properties_with_cam_js": sum(1 for v in cam_js_cache.values() if v),
        "rows_with_cam_js_available": cam_js_hits,
    }
    logger.info("Mechanical campaign structuring: %s", stats)
    return stats


def _parse_llm_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # try to find first {...}
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def classify_residuals_with_llm(max_workers: int = 5, use_batch: bool = False) -> int:
    """LLM only for rows that still have parse_ok=0 after mechanical pass."""
    if not DEEPSEEK_API_KEY or "your_deepseek_api_key" in DEEPSEEK_API_KEY:
        logger.info("Skipping LLM residual classification: API key not set.")
        return 0

    ensure_schema()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, campaign_type, title, content, target_period_text, target_condition_text
        FROM campaigns
        WHERE parse_ok IS NULL OR parse_ok = 0
        """
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        logger.info("No residual campaigns for LLM.")
        return 0

    logger.info("LLM residual structuring for %s campaigns", len(rows))

    if use_batch:
        return _llm_batch(rows)
    return _llm_realtime(rows, max_workers=max_workers)


def _llm_realtime(rows, max_workers: int = 5) -> int:
    client = DeepSeekClient()
    valid_plans = {"s_short", "short", "middle", "long", "all", "UNKNOWN"}
    valid_units = {"yen", "percent", "package", "pokkiri", "free_first_week", "unknown"}

    def _one(row):
        prompt = USER_PROMPT_TEMPLATE.format(
            campaign_type=row["campaign_type"] or "",
            title=row["title"] or "",
            content=row["content"] or "",
            period=row["target_period_text"] or "",
            condition=row["target_condition_text"] or "",
        )
        resp = client.chat(SYSTEM_PROMPT, prompt)
        return row["id"], _parse_llm_json(resp or "")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one, r): r for r in rows}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                logger.error("LLM residual error: %s", e)

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0
    for c_id, data in results:
        if not data:
            continue
        plan = data.get("target_plan_code") or "UNKNOWN"
        if plan not in valid_plans:
            plan = "UNKNOWN"
        unit = data.get("discount_unit") or "unknown"
        if unit not in valid_units:
            unit = "unknown"
        cursor.execute(
            """
            UPDATE campaigns SET
                target_plan_code = ?,
                discount_unit = ?,
                discount_value = ?,
                discount_max_yen = ?,
                period_max_days = ?,
                stay_min_days = ?,
                stay_max_days = ?,
                structure_source = 'llm_residual',
                parse_ok = 1,
                parse_warnings = ?
            WHERE id = ?
            """,
            (
                plan,
                unit,
                data.get("discount_value"),
                data.get("discount_max_yen"),
                data.get("period_max_days"),
                data.get("stay_min_days"),
                data.get("stay_max_days"),
                json.dumps(["filled_by_llm"], ensure_ascii=False),
                c_id,
            ),
        )
        updated += 1
    conn.commit()
    conn.close()
    logger.info("LLM residual updated %s campaigns", updated)
    return updated


def _llm_batch(rows) -> int:
    batch_client = DeepSeekBatchClient()
    tasks = []
    for row in rows:
        tasks.append(
            {
                "custom_id": str(row["id"]),
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": USER_PROMPT_TEMPLATE.format(
                    campaign_type=row["campaign_type"] or "",
                    title=row["title"] or "",
                    content=row["content"] or "",
                    period=row["target_period_text"] or "",
                    condition=row["target_condition_text"] or "",
                ),
            }
        )
    jsonl = batch_client.build_batch_jsonl(tasks)
    batch_id = batch_client.submit_batch(jsonl)
    if not batch_id:
        return 0
    status, _batch = batch_client.wait_for_completion(batch_id, poll_interval=15, timeout=1800)
    if status != "completed":
        return 0
    results = batch_client.get_results(batch_id) or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0
    for custom_id, text in results.items():
        data = _parse_llm_json(text)
        if not data:
            continue
        cursor.execute(
            """
            UPDATE campaigns SET
                target_plan_code = ?,
                discount_unit = ?,
                discount_value = ?,
                discount_max_yen = ?,
                period_max_days = ?,
                stay_min_days = ?,
                stay_max_days = ?,
                structure_source = 'llm_residual',
                parse_ok = 1,
                parse_warnings = ?
            WHERE id = ?
            """,
            (
                data.get("target_plan_code") or "UNKNOWN",
                data.get("discount_unit") or "unknown",
                data.get("discount_value"),
                data.get("discount_max_yen"),
                data.get("period_max_days"),
                data.get("stay_min_days"),
                data.get("stay_max_days"),
                json.dumps(["filled_by_llm"], ensure_ascii=False),
                int(custom_id),
            ),
        )
        updated += 1
    conn.commit()
    conn.close()
    return updated


def run_classification(
    use_batch: bool = False,
    realtime_workers: int = 5,
    use_llm_residuals: bool = False,
    force: bool = True,
) -> dict:
    """Full workflow: mechanical structure (+ optional LLM residuals)."""
    ensure_schema()
    logger.info("Starting campaign structuring workflow (mechanical primary)...")
    mech = classify_mechanically(force=force)

    llm_count = 0
    if use_llm_residuals:
        llm_count = classify_residuals_with_llm(
            max_workers=realtime_workers, use_batch=use_batch
        )

    # final residual count
    conn = get_db_connection()
    cursor = conn.cursor()
    residual = cursor.execute(
        "SELECT COUNT(*) AS c FROM campaigns WHERE parse_ok IS NULL OR parse_ok = 0"
    ).fetchone()["c"]
    by_plan = {
        r["target_plan_code"]: r["c"]
        for r in cursor.execute(
            "SELECT target_plan_code, COUNT(*) AS c FROM campaigns GROUP BY target_plan_code"
        )
    }
    by_unit = {
        r["discount_unit"]: r["c"]
        for r in cursor.execute(
            "SELECT discount_unit, COUNT(*) AS c FROM campaigns GROUP BY discount_unit"
        )
    }
    conn.close()

    result = {
        "status": "success",
        "mechanical": mech,
        "llm_residual_count": llm_count,
        "remaining_parse_fail": residual,
        "target_plan_code_dist": by_plan,
        "discount_unit_dist": by_unit,
    }
    logger.info("Campaign structuring finished: %s", result)
    return result


# Backwards-compatible aliases
def classify_with_llm_batch(timeout: int = 1800) -> int:
    return classify_residuals_with_llm(use_batch=True)


def classify_with_llm_realtime(max_workers: int = 5) -> int:
    return classify_residuals_with_llm(max_workers=max_workers, use_batch=False)


if __name__ == "__main__":
    run_classification(use_llm_residuals=False, force=True)
