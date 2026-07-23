"""Save raw HTML for re-parse."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime

from sources.base import FetchedPage
from store.repository import Repository

RAW_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw_pages_v2"
)


def save_raw_page(
    page: FetchedPage,
    *,
    source_site: str,
    repo: Repository | None = None,
    parser_version: str = "1.0",
) -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    content_hash = hashlib.sha256(page.html.encode("utf-8", errors="replace")).hexdigest()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{source_site}_{page.page_type}_{content_hash[:10]}_{ts}.html"
    path = os.path.join(RAW_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page.html)

    if repo is not None:
        conn = repo.connect()
        try:
            conn.execute(
                """
                INSERT INTO raw_pages
                (source_site, url, page_type, fetched_at, status_code, content_hash, storage_path, parser_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_site,
                    page.url,
                    page.page_type,
                    datetime.now().isoformat(),
                    page.status_code,
                    content_hash,
                    path,
                    parser_version,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return path
