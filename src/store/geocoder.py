"""Shared geocoding core (provider clients + entry point).

v1 の src/geocoder.py から、データレイヤ非依存の共有中核のみを移設したもの。
- GeocodingSystemError / clean_address / geocode_nominatim_single /
  geocode_nominatim_with_fallback / geocode_google / geocode_address
挙動は移設元から変更しない（docs/geocode-v2-batch-spec.md §5）。
"""

import os
import re
import sys
import time

import requests


class GeocodingSystemError(Exception):
    """Raised when geocoding fails due to temporary system, network, or auth errors."""
    pass

def clean_address(address: str) -> str:
    """
    Cleans Japanese address strings by stripping out building names, 
    apartment numbers, and room details.
    """
    if not address:
        return ""
    
    # Strip spaces
    addr = address.strip()
    
    # Normalize spaces: full-width space to half-width
    addr = addr.replace("　", " ")
    
    # Normalize hyphens: replace variations of long dashes and hyphens with standard '-'
    addr = re.sub(r'[－ー‐−―‐]', '-', addr)
    
    # Convert full-width numbers/alphabets to half-width
    zenkaku = "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    hankaku = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    trans_table = str.maketrans(zenkaku, hankaku)
    addr = addr.translate(trans_table)
    
    # If the address is split by spaces, evaluate the first token (often contains prefecture + town + numbers)
    parts = addr.split(" ")
    if parts:
        first_part = parts[0]
        # Ensure it actually looks like an address (has numbers or '丁目') to prevent discarding the whole address
        if re.search(r'\d', first_part) or "丁目" in first_part:
            addr = first_part
            
    # Remove building name attached without spaces
    # Matches prefecture/municipality/town and block numbers
    match = re.match(r'^([^\d]+(?:\d+丁目\d+番\d+号?|\d+丁目\d+番|\d+丁目|\d+番地?|\d+(?:-\d+)+|\d+))', addr)
    if match:
        addr = match.group(1)
        
    return addr.strip()

def geocode_nominatim_single(address: str) -> tuple[float | None, float | None]:
    """
    Performs a single request to Nominatim API to get lat/lng for an address.
    Raises GeocodingSystemError on network, timeout, or block issues.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "accept-language": "ja"
    }
    # Dedicated User-Agent to avoid blocking (required by Nominatim Usage Policy)
    headers = {
        "User-Agent": "yadokari-mut-app/1.0 (contact: orange.workspace@gmail.com)"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 403:
            raise GeocodingSystemError("Nominatim API blocked/403. Please check User-Agent.")
        if response.status_code == 429:
            raise GeocodingSystemError("Nominatim API Rate limited/429.")
        response.raise_for_status()
        data = response.json()
        if data:
            lat = float(data[0]["lat"])
            lng = float(data[0]["lon"])
            return lat, lng
    except requests.RequestException as e:
        raise GeocodingSystemError(f"Nominatim network error: {e}")
    return None, None

def geocode_nominatim_with_fallback(address: str) -> tuple[float | None, float | None, str | None, float | None]:
    """
    Queries Nominatim. If search fails, it falls back by removing trailing numbers
    or block details progressively to get coordinates of a wider area (e.g. town block).
    """
    cleaned = clean_address(address)
    if not cleaned:
        return None, None, None, None
        
    variants = [cleaned]
    current = cleaned
    
    # 1. Hyphen-separated number fallbacks (e.g., "4-22-1" -> "4-22" -> "4")
    while True:
        match = re.search(r'[-－]\d+$', current)
        if not match:
            break
        current = current[:match.start()]
        variants.append(current)
        
    # 2. Japanese character block fallbacks (e.g., "4丁目22番1号" -> "4丁目22番" -> "4丁目")
    current_jp = cleaned
    while True:
        # Strip "号"
        match_go = re.search(r'\d+号$', current_jp)
        if match_go:
            current_jp = current_jp[:match_go.start()]
            variants.append(current_jp.rstrip("番"))
            continue
        # Strip "番"
        match_ban = re.search(r'\d+番$', current_jp)
        if match_ban:
            current_jp = current_jp[:match_ban.start()]
            variants.append(current_jp.rstrip("丁目"))
            continue
        # Strip "丁目"
        match_cho = re.search(r'\d+丁目$', current_jp)
        if match_cho:
            current_jp = current_jp[:match_cho.start()]
            variants.append(current_jp)
            break
        break
        
    # Deduplicate while preserving order
    unique_variants = []
    for v in variants:
        v = v.strip()
        if v and v not in unique_variants:
            unique_variants.append(v)
            
    # Try geocoding each variant
    for idx, var in enumerate(unique_variants):
        # Enforce Nominatim rate limits (at least 1.2s delay between requests)
        if idx > 0:
            time.sleep(1.2)
            
        # Confidence decays as we query wider zones (0.9, 0.7, 0.5...)
        confidence = max(0.9 - (idx * 0.2), 0.3)
        
        lat, lng = geocode_nominatim_single(var)
        if lat and lng:
            return lat, lng, "nominatim", confidence
            
    return None, None, None, None

def geocode_google(address: str, api_key: str) -> tuple[float | None, float | None, str | None, float | None]:
    """
    Performs geocoding using Google Geocoding API.
    Raises GeocodingSystemError on network, timeout, auth or query limit issues.
    """
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": address,
        "key": api_key,
        "language": "ja"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        status = data.get("status")

        if status == "OK" and data.get("results"):
            result = data["results"][0]
            location = result["geometry"]["location"]
            loc_type = result["geometry"].get("location_type", "UNKNOWN")
            confidence = 1.0 if loc_type == "ROOFTOP" else 0.8
            return location["lat"], location["lng"], "google", confidence
        elif status == "ZERO_RESULTS":
            return None, None, "google", None
        else:
            raise GeocodingSystemError(f"Google API returned error status: {status}. Message: {data.get('error_message', '')}")
    except requests.RequestException as e:
        raise GeocodingSystemError(f"Google API network error: {e}")

def geocode_address(address: str, provider: str = None) -> tuple[float | None, float | None, str | None, float | None]:
    """
    Resolves coordinates for an address using Nominatim or Google Geocoding API.
    If provider is specified, routes strictly to that provider.
    On failure, returns (None, None, failed_provider_name, None).
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    
    # 1. Google explicitly selected
    if provider == "google":
        if not api_key:
            raise GeocodingSystemError("GOOGLE_MAPS_API_KEY is not configured but provider='google' was requested.")
        lat, lng, source, confidence = geocode_google(address, api_key)
        if lat and lng:
            return lat, lng, source, confidence
        return None, None, "google", None
        
    # 2. Nominatim explicitly selected
    if provider == "nominatim":
        lat, lng, source, confidence = geocode_nominatim_with_fallback(address)
        if lat and lng:
            return lat, lng, source, confidence
        return None, None, "nominatim", None
        
    # 3. Auto-detect (default behavior)
    if api_key:
        try:
            lat, lng, source, confidence = geocode_google(address, api_key)
            if lat and lng:
                return lat, lng, source, confidence
        except GeocodingSystemError as e:
            print(f"Google Geocoding failed due to system error: {e}. Falling back to Nominatim...", file=sys.stderr)
        
    lat, lng, source, confidence = geocode_nominatim_with_fallback(address)
    if lat and lng:
        return lat, lng, source, confidence
        
    last_source = "nominatim"
    return None, None, last_source, None
