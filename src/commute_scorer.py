import sys
import os
from database import get_db_connection
from campaign_active import (
    annotate_campaigns,
    compute_min_rent_from_plans,
    resolve_plans_effective_rent,
)

HUB_STATIONS = ["新宿", "渋谷", "東京", "品川", "池袋", "梅田", "難波", "心斎橋", "天王寺"]
DIRECT_LINES = ["山手線", "中央線", "総武線", "御堂筋線", "谷町線", "東西線", "丸ノ内線", "副都心線"]

_CAMPAIGN_SELECT = """
    campaign_type, title, content, target_period_text, target_condition_text,
    starts_on, ends_on, target_plan_code,
    discount_unit, discount_value, discount_max_yen, period_max_days,
    stay_min_days, stay_max_days, contract_within_days,
    package_rent_benefit_yen, package_cleaning_benefit_yen,
    package_fee_benefit_yen, package_total_benefit_yen,
    structure_source, parse_ok
"""


def _cheapest_effective_daily_rent(cursor, prop_id):
    """Min available plan daily rent after campaign-aware effective resolution."""
    cursor.execute(
        """
        SELECT plan_code, plan_name, available, campaign_label,
               original_daily_rent_yen, discounted_daily_rent_yen,
               original_total_yen, discounted_total_yen, total_period_days
        FROM rent_plans
        WHERE property_id = ?
        """,
        (prop_id,),
    )
    plans = [dict(r) for r in cursor.fetchall()]
    if not plans:
        return None

    cursor.execute(
        f"SELECT {_CAMPAIGN_SELECT} FROM campaigns WHERE property_id = ?",
        (prop_id,),
    )
    campaigns = [dict(r) for r in cursor.fetchall()]
    effective = resolve_plans_effective_rent(plans, annotate_campaigns(campaigns))
    mins = compute_min_rent_from_plans(effective)
    return mins.get("min_daily_rent")


def calculate_property_score(prop_id, cursor):
    """
    Calculates sub-scores and total score for a single property.
    Rent score uses effective (campaign-aware) cheapest daily rent.
    """
    # 1. Fetch property info
    cursor.execute("""
        SELECT built_year, area_m2, layout
        FROM properties WHERE id = ?
    """, (prop_id,))
    prop = cursor.fetchone()
    if not prop:
        return None

    # 2. Cheapest effective daily rent (expired campaigns → original)
    cheapest_rent = _cheapest_effective_daily_rent(cursor, prop_id)

    # 3. Best walk minutes
    cursor.execute("""
        SELECT MIN(walk_minutes) as min_walk
        FROM property_accesses
        WHERE property_id = ? AND walk_minutes IS NOT NULL
    """, (prop_id,))
    walk_row = cursor.fetchone()
    best_walk = walk_row["min_walk"] if walk_row else None

    # 4. Accesses details for commute score
    cursor.execute("""
        SELECT line_name, station_name
        FROM property_accesses
        WHERE property_id = ?
    """, (prop_id,))
    accesses = cursor.fetchall()

    # --- Scoring logic ---

    # Rent Score: cheaper is better [1500 to 6000 yen range]
    if cheapest_rent is None:
        rent_score = 50.0
    elif cheapest_rent <= 1500:
        rent_score = 100.0
    elif cheapest_rent >= 6000:
        rent_score = 0.0
    else:
        rent_score = 100.0 * (6000 - cheapest_rent) / (6000 - 1500)

    # Walk Score: closer is better [3 to 15 mins range]
    if best_walk is None:
        walk_score = 50.0
    elif best_walk <= 3:
        walk_score = 100.0
    elif best_walk >= 15:
        walk_score = 0.0
    else:
        walk_score = 100.0 * (15 - best_walk) / (15 - 3)

    # Area Score: bigger is better [15 to 35 m2 range]
    area = prop["area_m2"]
    if area is None:
        area_score = 50.0
    elif area <= 15.0:
        area_score = 0.0
    elif area >= 35.0:
        area_score = 100.0
    else:
        area_score = 100.0 * (area - 15.0) / (35.0 - 15.0)

    # Age Score: newer is better [1980 to 2026 range]
    year = prop["built_year"]
    if year is None:
        age_score = 50.0
    elif year <= 1980:
        age_score = 0.0
    elif year >= 2026:
        age_score = 100.0
    else:
        age_score = 100.0 * (year - 1980) / (2026 - 1980)

    # Commute Score
    commute_score = 50.0
    best_commute = 50.0
    for acc in accesses:
        line = acc["line_name"] or ""
        station = acc["station_name"] or ""

        score_val = 50.0
        # If the station is directly one of the hub stations
        if any(hub in station for hub in HUB_STATIONS):
            score_val = 100.0
        # If it is on Yamanote/Chuo/Sobu/etc. direct lines
        elif any(dl in line for dl in DIRECT_LINES):
            score_val = 80.0

        if score_val > best_commute:
            best_commute = score_val
    commute_score = best_commute

    # Calculate Total Score
    total_score = (
        rent_score * 0.35 +
        walk_score * 0.20 +
        area_score * 0.20 +
        age_score * 0.125 +
        commute_score * 0.125
    )

    return {
        "total_score": round(total_score, 2),
        "rent_score": round(rent_score, 2),
        "walk_score": round(walk_score, 2),
        "area_score": round(area_score, 2),
        "age_score": round(age_score, 2),
        "commute_score": round(commute_score, 2)
    }

def update_all_scores():
    """
    Recalculates and updates scores for all properties in the database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM properties")
    properties = cursor.fetchall()

    updated_count = 0
    for prop in properties:
        p_id = prop["id"]
        scores = calculate_property_score(p_id, cursor)
        if scores:
            cursor.execute("""
                UPDATE properties SET
                    total_score = ?,
                    rent_score = ?,
                    walk_score = ?,
                    area_score = ?,
                    age_score = ?,
                    commute_score = ?
                WHERE id = ?
            """, (
                scores["total_score"],
                scores["rent_score"],
                scores["walk_score"],
                scores["area_score"],
                scores["age_score"],
                scores["commute_score"],
                p_id
            ))
            updated_count += 1

    conn.commit()
    conn.close()
    print(f"Updated scores for {updated_count} properties.")

if __name__ == "__main__":
    update_all_scores()
