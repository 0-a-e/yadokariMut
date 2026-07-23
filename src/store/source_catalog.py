"""Catalog of ingest sources for admin UI / scrape-v2 (extensible)."""

from __future__ import annotations

import json
import os
from typing import Any

from store.pref_master import pref_display_name

# Declarative metadata — new sites only need a registry adapter + entry here
# (and optional config.json sources.<id> block).
SOURCE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "bratto",
        "display_name": "BraTTo",
        "description": "000area-weekly.com（全国）",
        "default_pages": 5,
        "supports_all_pages": True,
        "default_mark_inactive": True,
    },
    {
        "id": "unionmonthly",
        "display_name": "ユニオンマンスリー",
        "description": "unionmonthly.jp（東京・神奈川・千葉・埼玉・茨城）",
        "default_pages": None,  # None → all pages preferred for small footprint
        "supports_all_pages": True,
        "default_mark_inactive": True,
        "default_all_pages": True,
    },
    # Future (not registered yet — shown as unavailable until adapter exists):
    # {"id": "tokyomonthly", "display_name": "東京マンスリー", ...},
    # {"id": "tm21", "display_name": "東京マンスリー21", ...},
    # {"id": "goodmonthly", "display_name": "グッドマンスリー", ...},
]


def load_app_config() -> dict:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
    path = os.path.abspath(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _target_catalog_for_source(
    sid: str,
    cfg: dict,
    registered: dict,
) -> list[dict[str, str]]:
    """List crawl targets (prefectures) without pref_filter applied."""
    # Prefer config prefectures (full map) when present
    if isinstance(cfg, dict) and isinstance(cfg.get("prefectures"), dict):
        out = []
        for slug, meta in cfg["prefectures"].items():
            if isinstance(meta, dict):
                name = meta.get("name") or pref_display_name(slug)
            else:
                name = str(meta) if meta else pref_display_name(slug)
            out.append({"key": slug, "slug": slug, "name": name})
        return out

    if sid not in registered:
        return []
    try:
        # Do not pass pref_filter — we want the full catalog for admin UI
        clean = {k: v for k, v in (cfg or {}).items() if k != "pref_filter"}
        from sources.registry import SourceRegistry

        adapter = SourceRegistry.create(sid, clean)
        out = []
        for t in adapter.discover_list_targets():
            slug = t.prefecture_slug or t.key
            name = t.prefecture_name or pref_display_name(slug)
            out.append({"key": t.key, "slug": slug, "name": name})
        return out
    except Exception:
        return []


def _merge_targets(
    catalog_targets: list[dict[str, str]],
    db_by_slug: dict[str, dict[str, Any]],
    runs_by_key: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge adapter catalog + DB stats + latest scrape runs."""
    seen: set[str] = set()
    targets: list[dict[str, Any]] = []

    def build_one(key: str, slug: str, name: str) -> dict[str, Any]:
        stats = db_by_slug.get(slug) or db_by_slug.get(key) or {}
        run = runs_by_key.get(slug) or runs_by_key.get(key) or {}
        total = int(stats.get("total") or 0)
        active = int(stats.get("active") or 0)
        missing = int(stats.get("missing_coords") or 0)
        display_name = (
            name
            or stats.get("prefecture_name")
            or pref_display_name(slug)
            or slug
        )
        return {
            "key": key,
            "slug": slug,
            "name": display_name,
            "counts": {
                "total": total,
                "active": active,
                "missing_coords": missing,
            },
            "last_seen_at": stats.get("last_seen_at"),
            "last_detail_scraped_at": stats.get("last_detail_scraped_at"),
            "last_run_at": run.get("last_run_at"),
            "last_run_status": run.get("status"),
            "last_run_list_items": run.get("list_items"),
            "last_run_detail_ok": run.get("detail_ok"),
            "has_data": total > 0,
        }

    for t in catalog_targets:
        key = t["key"]
        slug = t.get("slug") or key
        seen.add(slug)
        seen.add(key)
        targets.append(build_one(key, slug, t.get("name") or ""))

    # Orphan DB rows (slug not in catalog) — still show for ops visibility
    for slug, stats in db_by_slug.items():
        if not slug or slug in seen:
            continue
        seen.add(slug)
        targets.append(
            build_one(
                slug,
                slug,
                stats.get("prefecture_name") or pref_display_name(slug),
            )
        )

    return targets


def list_source_admin_info() -> list[dict[str, Any]]:
    """Merge catalog + registry + config + DB counts + per-target status for admin API."""
    import sources  # noqa: F401
    from sources.registry import SourceRegistry
    from store.api_queries import SOURCE_DISPLAY, use_v2_data_layer
    from store.repository import Repository

    config = load_app_config()
    sources_cfg = config.get("sources") or {}
    registered = SourceRegistry.get_all()

    counts: dict[str, dict[str, int]] = {}
    counts_pref: dict[str, dict[str, dict[str, Any]]] = {}
    runs_pref: dict[str, dict[str, dict[str, Any]]] = {}

    if use_v2_data_layer():
        try:
            repo = Repository()
            # Ensure new tables exist (scrape_run_targets)
            try:
                repo.init_db()
            except Exception:
                pass
            conn = repo.connect()
            try:
                for row in conn.execute(
                    """
                    SELECT source_site,
                           COUNT(*) AS total,
                           SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
                           SUM(CASE WHEN is_active = 1 AND (lat IS NULL OR lng IS NULL) THEN 1 ELSE 0 END) AS missing_coords
                    FROM properties
                    GROUP BY source_site
                    """
                ):
                    counts[row["source_site"]] = {
                        "total": row["total"] or 0,
                        "active": row["active"] or 0,
                        "missing_coords": row["missing_coords"] or 0,
                    }
            finally:
                conn.close()
            try:
                counts_pref = repo.counts_by_prefecture()
                runs_pref = repo.latest_scrape_runs_by_target()
            except Exception:
                counts_pref = {}
                runs_pref = {}
        except Exception:
            pass

    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for entry in SOURCE_CATALOG:
        sid = entry["id"]
        seen_ids.add(sid)
        cfg = sources_cfg.get(sid) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        enabled = cfg.get("enabled", True)
        is_reg = sid in registered
        c = counts.get(sid, {})

        catalog_targets = _target_catalog_for_source(sid, cfg, registered)
        targets = _merge_targets(
            catalog_targets,
            counts_pref.get(sid) or {},
            runs_pref.get(sid) or {},
        )
        prefs = [t["slug"] for t in targets]

        out.append(
            {
                **entry,
                "display_name": entry.get("display_name")
                or SOURCE_DISPLAY.get(sid, sid),
                "enabled": bool(enabled) and is_reg,
                "registered": is_reg,
                "available": is_reg and bool(enabled),
                "prefectures": prefs,
                "targets": targets,
                "counts": {
                    "total": c.get("total", 0),
                    "active": c.get("active", 0),
                    "missing_coords": c.get("missing_coords", 0),
                },
            }
        )

    # Any registered adapter not in catalog yet
    for sid, cls in registered.items():
        if sid in seen_ids:
            continue
        cfg = sources_cfg.get(sid) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        c = counts.get(sid, {})
        catalog_targets = _target_catalog_for_source(sid, cfg, registered)
        targets = _merge_targets(
            catalog_targets,
            counts_pref.get(sid) or {},
            runs_pref.get(sid) or {},
        )
        out.append(
            {
                "id": sid,
                "display_name": getattr(cls, "display_name", None)
                or SOURCE_DISPLAY.get(sid, sid),
                "description": f"Registered adapter ({sid})",
                "default_pages": 5,
                "supports_all_pages": True,
                "default_mark_inactive": True,
                "enabled": True,
                "registered": True,
                "available": True,
                "prefectures": [t["slug"] for t in targets],
                "targets": targets,
                "counts": {
                    "total": c.get("total", 0),
                    "active": c.get("active", 0),
                    "missing_coords": c.get("missing_coords", 0),
                },
            }
        )

    return out


def resolve_scrape_sources(requested: list[str] | None) -> list[str]:
    """Expand 'all' / empty to available source ids; validate known ids."""
    catalog = list_source_admin_info()
    available = [s["id"] for s in catalog if s.get("available")]
    # Guard: accidental module / wrong type must not reach len()
    if requested is not None and not isinstance(requested, (list, tuple)):
        raise TypeError(
            f"sources must be a list of source ids, got {type(requested).__name__}"
        )
    if not requested or list(requested) == ["all"] or (
        len(requested) == 1 and requested[0] == "all"
    ):
        return available
    unknown = [s for s in requested if s not in {c["id"] for c in catalog}]
    if unknown:
        raise ValueError(f"Unknown source(s): {unknown}")
    unavailable = [s for s in requested if s not in available]
    if unavailable:
        raise ValueError(f"Source(s) not available (no adapter or disabled): {unavailable}")
    return list(requested)
