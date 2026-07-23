"""Geocode missing coordinates on v2 properties table."""

from __future__ import annotations

import time
from typing import Any, Optional

from geocoder import geocode_address
from store.repository import Repository


def geocode_missing_v2(
    limit: Optional[int] = 100,
    *,
    provider: Optional[str] = None,
) -> dict[str, Any]:
    repo = Repository()
    conn = repo.connect()
    try:
        sql = """
            SELECT id, address, title FROM properties
            WHERE address IS NOT NULL
              AND (lat IS NULL OR lng IS NULL)
              AND (geocode_source IS NULL OR geocode_source NOT LIKE 'failed%')
            ORDER BY id
        """
        rows = list(conn.execute(sql))
        if limit is not None:
            rows = rows[: int(limit)]
        if not rows:
            return {"total_found": 0, "processed": 0, "success": 0, "failed": 0}

        success = 0
        failed = 0
        for i, row in enumerate(rows):
            if i > 0:
                time.sleep(1.2 if provider != "google" else 0.1)
            address = row["address"]
            try:
                lat, lng, source, confidence = geocode_address(address, provider=provider)
                if lat is not None and lng is not None:
                    conn.execute(
                        """
                        UPDATE properties
                        SET lat = ?, lng = ?, geocode_source = ?, geocode_confidence = ?
                        WHERE id = ?
                        """,
                        (lat, lng, source, confidence, row["id"]),
                    )
                    success += 1
                else:
                    conn.execute(
                        "UPDATE properties SET geocode_source = ? WHERE id = ?",
                        (f"failed:{provider or 'default'}", row["id"]),
                    )
                    failed += 1
            except Exception:
                conn.execute(
                    "UPDATE properties SET geocode_source = ? WHERE id = ?",
                    (f"failed:{provider or 'default'}", row["id"]),
                )
                failed += 1
        conn.commit()
        return {
            "total_found": len(rows),
            "processed": success + failed,
            "success": success,
            "failed": failed,
        }
    finally:
        conn.close()
