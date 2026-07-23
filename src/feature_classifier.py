#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Feature/Amenity classification module.

Normalizes raw property feature names into standardized master names
(e.g., 'スマートTV' -> 'テレビ', 'ドラム式洗濯機' -> '洗濯機') using a two-stage process:
1. Regex-based mechanical matching
2. DeepSeek LLM-based categorization (Batch & Parallel Real-time API)
"""

import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection
from llm_client import DeepSeekClient, DeepSeekBatchClient, DEEPSEEK_API_KEY

logger = logging.getLogger(__name__)

# Standard feature categories and their mechanical mapping regex rules
FEATURE_RULES = {
    "テレビ": [r"テレビ", r"スマートtv", r"液晶tv", r"tv", r"テレビ台", r"tv台"],
    "エアコン": [r"エアコン", r"冷暖房", r"クーラー"],
    "洗濯機": [r"洗濯機", r"ドラム式", r"乾燥機付洗濯機"],
    "冷蔵庫": [r"冷蔵庫", r"2ドア冷蔵庫"],
    "電子レンジ": [r"電子レンジ", r"オーブンレンジ", r"レンジ"],
    "ベッド": [r"ベッド", r"シングルベッド", r"ダブルベッド", r"寝具"],
    "スマートロック": [r"スマートロック", r"デジタルキー", r"電子キー"],
    "オートロック": [r"オートロック"],
    "Wi-Fi": [r"wi-fi", r"wifi", r"インターネット", r"無線lan", r"ネット無料"],
    "バス・トイレ別": [r"バス[・]トイレ別", r"セパレート", r"風呂トイレ別"],
    "温水洗浄便座": [r"温水洗浄便座", r"ウォシュレット", r"シャワートイレ"],
    "浴室乾燥機": [r"浴室乾燥", r"浴室暖房換気乾燥"],
    "独立洗面台": [r"独立洗面", r"シャンプードレッサー", r"洗面化粧台"],
    "コンロ": [r"ガスコンロ", r"ihコンロ", r"システムキッチン", r"ihクッキングヒーター", r"2口コンロ", r"コンロ"],
    "駐輪場": [r"駐輪場", r"自転車置場"],
    "駐車場": [r"駐車場", r"パーキング"],
    "エレベーター": [r"エレベーター", r"ev"],
    "宅配ボックス": [r"宅配ボックス", r"宅配box"],
    "掃除機": [r"掃除機", r"クリーナー"],
    "ドライヤー": [r"ドライヤー", r"ヘアアイロン"],
    "炊飯器": [r"炊飯器", r"ジャー"],
    "ケトル": [r"ケトル", r"ポット", r"電気ケトル"],
    "ソファ": [r"ソファ", r"ソファー"]
}

SYSTEM_PROMPT = (
    "You are a real estate and property amenity normalization assistant. "
    "Your job is to take a raw feature/amenity name (e.g. 'ドラム式洗濯機', 'スマートTV', 'wifi無料', '駐輪場 要相談') "
    "and output a single, standardized, master feature name (e.g. '洗濯機', 'テレビ', 'Wi-Fi', '駐輪場'). "
    "Focus on extracting the core product or service. Do not translate English brands or modify standard English technical names like 'Bluetooth'. "
    "If the input is already simple or doesn't belong to any common categories, return the input itself or 'UNKNOWN' if it is noise.\n\n"
    "Respond ONLY with the normalized master feature name. "
    "Do not include quotes, explanations, markdown, or code blocks."
)

USER_PROMPT_TEMPLATE = (
    "Raw feature name: {feature_name}\n"
    "Category context: {category}\n\n"
    "Standardized master name:"
)


def ensure_schema():
    """Checks if the normalized_name column exists in property_features, and adds it if missing."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(property_features)")
    columns = [row["name"] for row in cursor.fetchall()]
    
    if "normalized_name" not in columns:
        logger.info("Adding column 'normalized_name' to 'property_features' table...")
        cursor.execute("ALTER TABLE property_features ADD COLUMN normalized_name TEXT")
        conn.commit()
        logger.info("Column added successfully.")
    
    conn.close()


def classify_mechanically() -> int:
    """Classifies property features using regex keyword matching.
    
    Returns:
        The number of successfully classified records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, feature_name FROM property_features WHERE normalized_name IS NULL")
    rows = cursor.fetchall()
    
    classified_count = 0
    for row in rows:
        f_id = row["id"]
        f_name = row["feature_name"] or ""
        f_name_lower = f_name.lower()
        
        matched_name = None
        for std_name, patterns in FEATURE_RULES.items():
            for pattern in patterns:
                if re.search(pattern, f_name_lower, re.IGNORECASE):
                    matched_name = std_name
                    break
            if matched_name:
                break
                
        if matched_name:
            cursor.execute("UPDATE property_features SET normalized_name = ? WHERE id = ?", (matched_name, f_id))
            classified_count += 1
            
    conn.commit()
    conn.close()
    
    logger.info(f"Mechanical classification completed. Normalized {classified_count} feature records.")
    return classified_count


def classify_with_llm_batch(timeout: int = 1800) -> int:
    """Classifies unique unclassified features using DeepSeek Batch API.
    
    Returns:
        The number of successfully classified records.
    """
    if not DEEPSEEK_API_KEY or "your_deepseek_api_key" in DEEPSEEK_API_KEY:
        logger.warning("Skipping LLM classification: DeepSeek API key is not set in .env")
        return 0

    ensure_schema()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # Query unique raw feature names that are not yet normalized
    cursor.execute("""
        SELECT DISTINCT feature_name, feature_category 
        FROM property_features 
        WHERE normalized_name IS NULL
    """)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        logger.info("No unclassified unique features left for LLM processing.")
        return 0

    logger.info(f"Found {len(rows)} unique features to classify via DeepSeek Batch API.")
    
    batch_client = DeepSeekBatchClient()
    tasks = []
    
    # Use indexing or hash of name as custom_id
    for idx, row in enumerate(rows):
        tasks.append({
            "custom_id": f"feat_{idx}",
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": USER_PROMPT_TEMPLATE.format(
                feature_name=row["feature_name"] or "",
                category=row["feature_category"] or "other"
            )
        })
        
    jsonl_content = batch_client.build_batch_jsonl(tasks)
    
    batch_id = batch_client.submit_batch(jsonl_content)
    if not batch_id:
        logger.error("Failed to submit batch job to DeepSeek.")
        return 0
        
    status, batch = batch_client.wait_for_completion(batch_id, poll_interval=15, timeout=timeout)
    if status != "completed":
        logger.error(f"Batch job failed or timed out with status: {status}")
        return 0
        
    results = batch_client.get_results(batch_id)
    if not results:
        logger.warning("No results returned from the Batch job.")
        return 0
        
    # Map back custom_id to feature_name and update DB
    conn = get_db_connection()
    cursor = conn.cursor()
    updated_count = 0
    
    for idx, row in enumerate(rows):
        task_id = f"feat_{idx}"
        normalized = results.get(task_id)
        if normalized:
            normalized = normalized.strip().strip("'\"` ")
            if normalized == "UNKNOWN":
                normalized = row["feature_name"] # Fallback to original
            
            cursor.execute("""
                UPDATE property_features 
                SET normalized_name = ? 
                WHERE feature_name = ? AND normalized_name IS NULL
            """, (normalized, row["feature_name"]))
            updated_count += cursor.rowcount
            
    conn.commit()
    conn.close()
    
    logger.info(f"LLM Batch feature classification completed. Updated {updated_count} records.")
    return updated_count


def classify_with_llm_realtime(max_workers: int = 5) -> int:
    """Classifies unique unclassified features using real-time API concurrently.
    
    Returns:
        The number of successfully classified records.
    """
    if not DEEPSEEK_API_KEY or "your_deepseek_api_key" in DEEPSEEK_API_KEY:
        logger.warning("Skipping LLM classification: DeepSeek API key is not set in .env")
        return 0

    ensure_schema()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT feature_name, feature_category 
        FROM property_features 
        WHERE normalized_name IS NULL
    """)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        logger.info("No unclassified unique features left for LLM processing.")
        return 0

    logger.info(f"Found {len(rows)} unique features to classify via DeepSeek Real-time concurrent API.")
    
    client = DeepSeekClient()
    
    def _classify_single(row):
        f_name = row["feature_name"] or ""
        cat = row["feature_category"] or "other"
        user_prompt = USER_PROMPT_TEMPLATE.format(feature_name=f_name, category=cat)
        response = client.chat(SYSTEM_PROMPT, user_prompt)
        if response:
            normalized = response.strip().strip("'\"` ")
            return f_name, normalized
        return f_name, None

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_classify_single, row): row for row in rows}
        for future in as_completed(futures):
            try:
                f_name, normalized = future.result()
                if normalized:
                    results.append((f_name, normalized))
            except Exception as e:
                logger.error(f"Error classifying single feature: {e}")

    # Update DB
    conn = get_db_connection()
    cursor = conn.cursor()
    updated_count = 0
    
    for f_name, normalized in results:
        if normalized == "UNKNOWN":
            normalized = f_name
        cursor.execute("""
            UPDATE property_features 
            SET normalized_name = ? 
            WHERE feature_name = ? AND normalized_name IS NULL
        """, (normalized, f_name))
        updated_count += cursor.rowcount
        
    conn.commit()
    conn.close()
    
    logger.info(f"LLM Real-time feature classification completed. Updated {updated_count} records.")
    return updated_count


def run_feature_classification(use_batch: bool = True, realtime_workers: int = 5) -> dict:
    """Runs the full feature normalization workflow.
    
    Returns:
        A dict containing status and count details.
    """
    ensure_schema()
    
    logger.info("Starting property features classification workflow...")
    
    # 1. Mechanical match
    mechanic_count = classify_mechanically()
    
    # 2. LLM match for the remaining unique features
    llm_count = 0
    if DEEPSEEK_API_KEY and "your_deepseek_api_key" not in DEEPSEEK_API_KEY:
        if use_batch:
            llm_count = classify_with_llm_batch()
        else:
            llm_count = classify_with_llm_realtime(max_workers=realtime_workers)
    else:
        logger.info("DeepSeek API Key is not set or placeholder. Skipping LLM stage.")
        
    total_updated = mechanic_count + llm_count
    logger.info(f"Feature classification finished. Total updated: {total_updated} (Mechanical: {mechanic_count}, LLM: {llm_count})")
    
    return {
        "status": "success",
        "mechanical_count": mechanic_count,
        "llm_count": llm_count,
        "total_count": total_updated
    }


if __name__ == "__main__":
    run_feature_classification(use_batch=False)
