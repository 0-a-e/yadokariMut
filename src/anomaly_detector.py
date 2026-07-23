import sys
import os
from database import get_db_connection

# Latitude and Longitude bounding boxes for prefectures
PREFECTURE_BOUNDS = {
    "東京都": {
        "min_lat": 35.4, "max_lat": 35.9,
        "min_lng": 139.0, "max_lng": 140.2
    },
    "大阪府": {
        "min_lat": 34.2, "max_lat": 35.1,
        "min_lng": 135.1, "max_lng": 135.8
    }
}

def detect_anomalies(property_id=None):
    """
    Scans the database for anomalies in properties and pricing.
    If property_id is specified, only checks that property.
    Returns a dictionary of anomalies where keys are property IDs.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT p.id, p.source_property_id, p.title, p.address, p.prefecture_name, p.lat, p.lng, p.detail_url
        FROM properties p
    """
    params = []
    if property_id:
        query += " WHERE p.id = ?"
        params.append(property_id)
        
    cursor.execute(query, params)
    properties = cursor.fetchall()
    
    anomalies = {}
    
    for prop in properties:
        p_id = prop["id"]
        prop_anomalies = []
        
        # 1. Check Lat/Lng bounds
        lat = prop["lat"]
        lng = prop["lng"]
        pref = prop["prefecture_name"]
        
        if lat is not None and lng is not None:
            bounds = PREFECTURE_BOUNDS.get(pref)
            if bounds:
                if not (bounds["min_lat"] <= lat <= bounds["max_lat"]) or not (bounds["min_lng"] <= lng <= bounds["max_lng"]):
                    prop_anomalies.append({
                        "type": "geo_out_of_bounds",
                        "message": f"Coordinates ({lat}, {lng}) are outside bounds for {pref}"
                    })
            else:
                # Basic Japan bounds
                if not (30.0 <= lat <= 46.0) or not (128.0 <= lng <= 150.0):
                    prop_anomalies.append({
                        "type": "geo_out_of_bounds",
                        "message": f"Coordinates ({lat}, {lng}) are outside Japan bounds"
                    })
        elif prop["prefecture_name"]:
            # Missing coordinates
            prop_anomalies.append({
                "type": "geo_missing",
                "message": "Coordinates are missing/NULL"
            })
            
        # 2. Check Price anomalies
        cursor.execute("""
            SELECT plan_name, original_daily_rent_yen, discounted_daily_rent_yen 
            FROM rent_plans 
            WHERE property_id = ? AND available = 1
        """, (p_id,))
        plans = cursor.fetchall()
        
        for plan in plans:
            daily = plan["discounted_daily_rent_yen"]
            if daily is not None:
                if daily < 500:
                    prop_anomalies.append({
                        "type": "price_too_low",
                        "message": f"Daily rent for plan '{plan['plan_name']}' is extremely low: {daily} yen"
                    })
                elif daily > 50000:
                    prop_anomalies.append({
                        "type": "price_too_high",
                        "message": f"Daily rent for plan '{plan['plan_name']}' is extremely high: {daily} yen"
                    })
                    
        # 3. Check Address anomalies (e.g. address region doesn't match prefecture)
        addr = prop["address"]
        if addr and pref:
            if pref not in addr:
                prop_anomalies.append({
                    "type": "address_mismatch",
                    "message": f"Address '{addr}' does not mention prefecture '{pref}'"
                })
                
        if prop_anomalies:
            anomalies[p_id] = {
                "property_id": p_id,
                "source_property_id": prop["source_property_id"],
                "title": prop["title"],
                "detail_url": prop["detail_url"],
                "anomalies": prop_anomalies
            }
            
    conn.close()
    return anomalies

if __name__ == "__main__":
    anoms = detect_anomalies()
    print(f"Found anomalies in {len(anoms)} properties:")
    for pid, details in anoms.items():
        print(f"Property ID {pid} ({details['title']}):")
        for a in details["anomalies"]:
            print(f"  - [{a['type']}] {a['message']}")
