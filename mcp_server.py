import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from typing import Optional

from mcp.server.fastmcp import FastMCP

from services import (
    db_compare_properties,
    db_export_geojson,
    db_export_kml,
    db_get_property_detail,
    db_search_properties,
    db_update_shortlist,
)


mcp = FastMCP(
    "yadokari-mut",
    instructions=(
        "Search, compare, shortlist, and export monthly apartment properties "
        "from the local YadokariMut SQLite database."
    ),
    log_level="ERROR",
)


@mcp.tool()
def search_properties(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    plan_code: Optional[str] = None,
    station_names: Optional[list[str]] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[list[str]] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    limit: int = 50,
) -> list[dict]:
    """Search properties with structured filters."""
    return db_search_properties(
        {
            "prefecture_name": prefecture_name,
            "max_monthly_total_yen": max_monthly_total_yen,
            "plan_code": plan_code,
            "station_names": station_names,
            "max_walk_minutes": max_walk_minutes,
            "min_area_m2": min_area_m2,
            "required_features": required_features,
            "saved_only": saved_only,
            "exclude_hidden": exclude_hidden,
            "limit": limit,
        }
    )


@mcp.tool()
def get_property_detail(property_id: str) -> Optional[dict]:
    """Fetch complete details for a property by SQLite id or source room_id."""
    return db_get_property_detail(property_id)


@mcp.tool()
def compare_properties(property_ids: list[str]) -> dict:
    """Compare multiple properties side by side."""
    return db_compare_properties(property_ids)


@mcp.tool()
def update_shortlist(property_id: str, status: str, comment: Optional[str] = None) -> dict:
    """Set shortlist status for a property. Status must be saved, hide, reject, or none."""
    return db_update_shortlist(property_id, status, comment)


@mcp.tool()
def export_geojson(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    plan_code: Optional[str] = None,
    station_names: Optional[list[str]] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[list[str]] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    file_path: Optional[str] = None,
) -> dict:
    """Export filtered properties as a GeoJSON file for map viewing."""
    params = {
        "prefecture_name": prefecture_name,
        "max_monthly_total_yen": max_monthly_total_yen,
        "plan_code": plan_code,
        "station_names": station_names,
        "max_walk_minutes": max_walk_minutes,
        "min_area_m2": min_area_m2,
        "required_features": required_features,
        "saved_only": saved_only,
        "exclude_hidden": exclude_hidden,
    }
    return db_export_geojson(params, file_path)


@mcp.tool()
def export_kml(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    plan_code: Optional[str] = None,
    station_names: Optional[list[str]] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[list[str]] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    file_path: Optional[str] = None,
) -> dict:
    """Export filtered properties as a KML file for Google Earth/My Maps."""
    params = {
        "prefecture_name": prefecture_name,
        "max_monthly_total_yen": max_monthly_total_yen,
        "plan_code": plan_code,
        "station_names": station_names,
        "max_walk_minutes": max_walk_minutes,
        "min_area_m2": min_area_m2,
        "required_features": required_features,
        "saved_only": saved_only,
        "exclude_hidden": exclude_hidden,
    }
    return db_export_kml(params, file_path)


@mcp.tool()
def geocode_properties(
    limit: Optional[int] = 20,
    force: bool = False,
    provider: Optional[str] = None,
    retry_only: bool = False,
    filter_expr: Optional[str] = None,
) -> dict:
    """Geocode properties in the database that are missing coordinates. Useful to fix map display exclusions."""
    from geocoder import geocode_missing_properties
    try:
        stats = geocode_missing_properties(
            limit=limit,
            force=force,
            provider=provider,
            retry_only=retry_only,
            filter_expr=filter_expr
        )
        remaining = stats.get("remaining", 0)
        if remaining > 0:
            message = (
                f"Geocoding batch executed. Processed {stats['processed']} properties "
                f"(Success: {stats['success']}, Failed: {stats['failed']}). "
                f"Note: {remaining} properties are still remaining and need geocoding."
            )
        else:
            message = f"Geocoding completed. All {stats['total_found']} matching properties have been processed."
            
        return {
            "status": "success",
            "message": message,
            "details": stats
        }
    except Exception as e:
        return {"status": "error", "message": f"Geocoding execution failed: {str(e)}"}


def run_mcp_server():
    """Run the official MCP stdio server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
