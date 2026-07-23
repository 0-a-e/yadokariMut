import os
import time
import re
import sys
import requests
from database import get_db_connection

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

class Node:
    def to_sql(self) -> tuple[str, list]:
        raise NotImplementedError

class IdentifierNode(Node):
    def __init__(self, name: str):
        self.name = name.lower()
        
    def to_sql(self) -> tuple[str, list]:
        if self.name == "missing":
            return "(lat IS NULL OR lng IS NULL)", []
        elif self.name == "resolved":
            return "(lat IS NOT NULL AND lng IS NOT NULL)", []
        elif self.name == "failed":
            return "(geocode_source LIKE 'failed:%')", []
        else:
            return "geocode_source = ?", [self.name]

class NotNode(Node):
    def __init__(self, operand: Node):
        self.operand = operand
        
    def to_sql(self) -> tuple[str, list]:
        sql, params = self.operand.to_sql()
        return f"(NOT {sql})", params

class BinaryOpNode(Node):
    def __init__(self, left: Node, op: str, right: Node):
        self.left = left
        self.op = op.upper()
        self.right = right
        
    def to_sql(self) -> tuple[str, list]:
        left_sql, left_params = self.left.to_sql()
        right_sql, right_params = self.right.to_sql()
        
        if self.op == "AND":
            return f"({left_sql} AND {right_sql})", left_params + right_params
        elif self.op == "OR":
            return f"({left_sql} OR {right_sql})", left_params + right_params
        elif self.op == "XOR":
            # SQLite does not support native XOR. We expand it as (A OR B) AND NOT (A AND B)
            # Duplicate parameter lists to maintain parameter positional alignment.
            return (
                f"(({left_sql} OR {right_sql}) AND NOT ({left_sql} AND {right_sql}))",
                left_params + right_params + left_params + right_params
            )
        raise ValueError(f"Unknown operator: {self.op}")

class FilterParser:
    """Recursively descends logical expressions into AST nodes."""
    def __init__(self, expression: str):
        token_pattern = r'\(|\)|AND|OR|NOT|XOR|[a-zA-Z0-9_\-:]+'
        self.tokens = re.findall(token_pattern, expression, re.IGNORECASE)
        self.pos = 0
        
    def peek(self) -> str | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None
        
    def consume(self, expected: str = None) -> str:
        tok = self.peek()
        if not tok:
            raise ValueError("Unexpected end of expression")
        if expected and tok.upper() != expected.upper():
            raise ValueError(f"Expected token {expected}, got {tok}")
        self.pos += 1
        return tok
        
    def parse(self) -> Node:
        node = self.expression()
        if self.peek() is not None:
            raise ValueError(f"Unexpected token at end of expression: {self.peek()}")
        return node
        
    def expression(self) -> Node:
        node = self.term()
        while self.peek() and self.peek().upper() in ("OR", "XOR"):
            op = self.consume()
            right = self.term()
            node = BinaryOpNode(node, op, right)
        return node
        
    def term(self) -> Node:
        node = self.factor()
        while self.peek() and self.peek().upper() == "AND":
            op = self.consume()
            right = self.factor()
            node = BinaryOpNode(node, op, right)
        return node
        
    def factor(self) -> Node:
        tok = self.peek()
        if tok and tok.upper() == "NOT":
            self.consume()
            operand = self.factor()
            return NotNode(operand)
        return self.primary()
        
    def primary(self) -> Node:
        tok = self.peek()
        if not tok:
            raise ValueError("Unexpected end of expression in primary")
        if tok == "(":
            self.consume()
            node = self.expression()
            self.consume(")")
            return node
        else:
            name = self.consume()
            return IdentifierNode(name)

def parse_filter_to_sql(expression: str) -> tuple[str, list]:
    """Helper to convert string filters to SQLite query blocks safely."""
    if not expression or not expression.strip():
        return "1=1", []
    parser = FilterParser(expression)
    ast_root = parser.parse()
    return ast_root.to_sql()

def geocode_missing_properties(
    limit: int = None, 
    force: bool = False, 
    provider: str = None, 
    retry_only: bool = False,
    filter_expr: str = None
) -> dict:
    """
    Finds properties in the database that match targeting filters, resolves them,
    and updates the DB. On failure, it records which provider failed to avoid redundant retries.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT id, address, title FROM properties WHERE address IS NOT NULL"
    params = []
    
    if filter_expr:
        # Use logical expression AST parser
        sql_cond, sql_params = parse_filter_to_sql(filter_expr)
        query += f" AND ({sql_cond})"
        params.extend(sql_params)
    elif retry_only:
        # Retry mode: Target properties previously geocoded or marked failed by the chosen provider(s).
        # We also include any failed attempts from other providers so they can be retried/recovered with the current provider.
        if provider == "nominatim":
            query += " AND (geocode_source IN ('nominatim', 'failed:nominatim') OR geocode_source LIKE 'failed:%')"
        elif provider == "google":
            query += " AND (geocode_source IN ('google', 'failed:google') OR geocode_source LIKE 'failed:%')"
        else:
            # Targets all geocoded sources or failed sources
            query += " AND (geocode_source IN ('nominatim', 'google') OR geocode_source LIKE 'failed:%')"
    elif force:
        # Force mode: Target all properties with address
        pass
    else:
        # Default mode: Target properties missing coordinates and not already failed
        query += """ AND (lat IS NULL OR lng IS NULL)
                     AND (geocode_source IS NULL OR geocode_source NOT LIKE 'failed%')"""
                     
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    if not rows:
        print("No properties need geocoding with the specified criteria.")
        conn.close()
        return {
            "total_found": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "remaining": 0
        }
        
    print(f"Found {len(rows)} properties to geocode (provider={provider}, retry_only={retry_only}, filter={filter_expr}).")
    
    count = 0
    success = 0
    failed_count = 0
    
    for row in rows:
        if limit and count >= limit:
            print(f"Reached limit of {limit} geocoding operations.")
            break
            
        p_id = row["id"]
        address = row["address"]
        title = row["title"]
        
        print(f"[{count+1}/{len(rows)}] Geocoding: {title} ({address})")
        
        # Inter-request delay to honor API usage policies
        if count > 0:
            if provider == "google":
                time.sleep(0.1)
            else:
                time.sleep(1.2)
            
        try:
            lat, lng, source, confidence = geocode_address(address, provider=provider)
        except GeocodingSystemError as e:
            print(f"  -> SKIPPED (System Error): {e}")
            count += 1
            continue
            
        if lat and lng:
            cursor.execute("""
                UPDATE properties
                SET lat = ?, lng = ?, geocode_source = ?, geocode_confidence = ?
                WHERE id = ?
            """, (lat, lng, source, confidence, p_id))
            conn.commit()
            success += 1
            print(f"  -> SUCCESS: lat={lat}, lng={lng} (source={source}, confidence={confidence})")
        else:
            # Determine failed provider source
            failed_source = source if source else (provider if provider else "nominatim")
            failed_status = f"failed:{failed_source}"
            
            cursor.execute("""
                UPDATE properties
                SET lat = NULL, lng = NULL, geocode_source = ?, geocode_confidence = NULL
                WHERE id = ?
            """, (failed_status, p_id))
            conn.commit()
            failed_count += 1
            print(f"  -> FAILED: Marked geocode_source = '{failed_status}' in database")
            
        count += 1
        
    remaining = max(0, len(rows) - count)
    conn.close()
    print(f"Geocoding batch completed. Updated: {success} success, {failed_count} marked as failed out of {count} processed.")
    return {
        "total_found": len(rows),
        "processed": count,
        "success": success,
        "failed": failed_count,
        "remaining": remaining
    }

if __name__ == "__main__":
    geocode_missing_properties()
