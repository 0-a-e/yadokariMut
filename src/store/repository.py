"""Repository for multi-source v2 SQLite store."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from domain.models import PropertyDraft
from domain.pricing import compute_catalog_min_daily, resolve_plans_effective
from store.schema import init_schema

def default_db_path() -> str:
    return os.environ.get(
        "YADOKARIMUT_V2_DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "yadokari_mut_v2.db"),
    )


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


class Repository:
    """Thin data access for v2 schema. Does not scrape."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or default_db_path()

    def connect(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def init_db(self) -> None:
        conn = self.connect()
        try:
            init_schema(conn)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert_property(self, draft: PropertyDraft) -> int:
        """Insert or update a property and replace child rows. Returns property id."""
        conn = self.connect()
        try:
            return self._upsert_property_conn(conn, draft)
        finally:
            conn.close()

    def _upsert_property_conn(self, conn: sqlite3.Connection, draft: PropertyDraft) -> int:
        now = datetime.now().isoformat()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, first_seen_at FROM properties WHERE source_site = ? AND external_id = ?",
            (draft.source_site, draft.external_id),
        )
        row = cur.fetchone()
        if row:
            property_id = row["id"]
            first_seen_at = row["first_seen_at"] or now
        else:
            property_id = None
            first_seen_at = now

        # Catalog cache from resolved plans
        resolved_plans = resolve_plans_effective(draft.price_plans)
        catalog = compute_catalog_min_daily(resolved_plans)
        catalog_daily = catalog.get("catalog_rent_per_day_yen")

        cur.execute(
            """
            INSERT INTO properties (
                id, source_site, external_id, entity_type, title, detail_url,
                prefecture_slug, prefecture_name, municipality, address,
                lat, lng, geocode_source, geocode_confidence,
                layout, area_m2, area_m2_max, built_year, built_month,
                construction_year_text, capacity_text, structure, floors_text,
                floor_number, point_text, availability_text, min_stay_days,
                contract_fee_yen, first_seen_at, last_seen_at, detail_scraped_at,
                is_active, catalog_rent_per_day_yen
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?
            )
            ON CONFLICT(source_site, external_id) DO UPDATE SET
                entity_type = excluded.entity_type,
                title = excluded.title,
                detail_url = excluded.detail_url,
                prefecture_slug = excluded.prefecture_slug,
                prefecture_name = excluded.prefecture_name,
                municipality = excluded.municipality,
                address = excluded.address,
                lat = COALESCE(excluded.lat, properties.lat),
                lng = COALESCE(excluded.lng, properties.lng),
                geocode_source = COALESCE(excluded.geocode_source, properties.geocode_source),
                geocode_confidence = COALESCE(excluded.geocode_confidence, properties.geocode_confidence),
                layout = excluded.layout,
                area_m2 = excluded.area_m2,
                area_m2_max = excluded.area_m2_max,
                built_year = excluded.built_year,
                built_month = excluded.built_month,
                construction_year_text = excluded.construction_year_text,
                capacity_text = excluded.capacity_text,
                structure = excluded.structure,
                floors_text = excluded.floors_text,
                floor_number = excluded.floor_number,
                point_text = excluded.point_text,
                availability_text = excluded.availability_text,
                min_stay_days = excluded.min_stay_days,
                contract_fee_yen = excluded.contract_fee_yen,
                last_seen_at = excluded.last_seen_at,
                detail_scraped_at = COALESCE(excluded.detail_scraped_at, properties.detail_scraped_at),
                is_active = excluded.is_active,
                catalog_rent_per_day_yen = excluded.catalog_rent_per_day_yen
            """,
            (
                property_id,
                draft.source_site,
                draft.external_id,
                draft.entity_type,
                draft.title,
                draft.detail_url,
                draft.prefecture_slug,
                draft.prefecture_name,
                draft.municipality,
                draft.address,
                draft.lat,
                draft.lng,
                draft.geocode_source,
                draft.geocode_confidence,
                draft.layout,
                draft.area_m2,
                draft.area_m2_max,
                draft.built_year,
                draft.built_month,
                draft.construction_year_text,
                draft.capacity_text,
                draft.structure,
                draft.floors_text,
                draft.floor_number,
                draft.point_text,
                draft.availability_text,
                draft.min_stay_days,
                draft.contract_fee_yen,
                first_seen_at,
                now,
                draft.detail_scraped_at,
                1 if draft.is_active else 0,
                catalog_daily,
            ),
        )
        if not property_id:
            property_id = cur.lastrowid

        # Replace children
        cur.execute("DELETE FROM property_accesses WHERE property_id = ?", (property_id,))
        for a in draft.accesses:
            cur.execute(
                """
                INSERT INTO property_accesses
                (property_id, line_name, station_name, walk_minutes, raw_text, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (property_id, a.line_name, a.station_name, a.walk_minutes, a.raw_text, a.sort_order),
            )

        cur.execute("DELETE FROM property_images WHERE property_id = ?", (property_id,))
        for i, img in enumerate(draft.images):
            cur.execute(
                """
                INSERT OR IGNORE INTO property_images
                (property_id, image_url, image_type, alt_text, sort_order, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (property_id, img.image_url, img.image_type, img.alt_text, img.sort_order or i, now),
            )

        cur.execute("DELETE FROM property_links WHERE property_id = ?", (property_id,))
        for link in draft.links:
            cur.execute(
                """
                INSERT OR IGNORE INTO property_links
                (property_id, link_type, url, label, scraped_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (property_id, link.link_type, link.url, link.label, now),
            )

        cur.execute("DELETE FROM property_features WHERE property_id = ?", (property_id,))
        for f in draft.features:
            cur.execute(
                """
                INSERT OR IGNORE INTO property_features
                (property_id, feature_name, feature_category, raw_text)
                VALUES (?, ?, ?, ?)
                """,
                (property_id, f.feature_name, f.feature_category, f.raw_text),
            )

        cur.execute("DELETE FROM price_plans WHERE property_id = ?", (property_id,))
        for p in draft.price_plans:
            cur.execute(
                """
                INSERT INTO price_plans (
                    property_id, plan_key, plan_name, duration_min_days, duration_max_days,
                    available, presentation_unit, rent_original_yen, rent_current_yen,
                    management_yen, utilities_yen, utilities_included, cleaning_yen,
                    campaign_label, raw_text, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    property_id,
                    p.plan_key,
                    p.plan_name,
                    p.duration_min_days,
                    p.duration_max_days,
                    1 if p.available else 0,
                    p.presentation_unit,
                    p.rent_original_yen,
                    p.rent_current_yen,
                    p.management_yen,
                    p.utilities_yen,
                    1 if p.utilities_included else 0,
                    p.cleaning_yen,
                    p.campaign_label,
                    p.raw_text,
                    now,
                ),
            )

        cur.execute("DELETE FROM campaigns WHERE property_id = ?", (property_id,))
        for c in draft.campaigns:
            cur.execute(
                """
                INSERT INTO campaigns (
                    property_id, campaign_type, title, content,
                    target_period_text, target_condition_text, starts_on, ends_on,
                    target_plan_key, discount_unit, discount_value, discount_max_yen,
                    period_max_days, stay_min_days, stay_max_days, contract_within_days,
                    package_rent_benefit_yen, package_cleaning_benefit_yen,
                    package_fee_benefit_yen, package_total_benefit_yen,
                    structure_source, parse_ok, parse_warnings, raw_json, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    property_id,
                    c.campaign_type,
                    c.title,
                    c.content,
                    c.target_period_text,
                    c.target_condition_text,
                    c.starts_on,
                    c.ends_on,
                    c.target_plan_key,
                    c.discount_unit,
                    c.discount_value,
                    c.discount_max_yen,
                    c.period_max_days,
                    c.stay_min_days,
                    c.stay_max_days,
                    c.contract_within_days,
                    c.package_rent_benefit_yen,
                    c.package_cleaning_benefit_yen,
                    c.package_fee_benefit_yen,
                    c.package_total_benefit_yen,
                    c.structure_source,
                    c.parse_ok,
                    c.parse_warnings,
                    c.raw_json,
                    now,
                ),
            )

        cur.execute(
            """
            INSERT INTO property_snapshots (
                property_id, scraped_at, is_active, catalog_rent_per_day_yen,
                raw_list_json, raw_detail_json, raw_html_path, parser_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                property_id,
                now,
                1 if draft.is_active else 0,
                catalog_daily,
                draft.raw_list_json,
                draft.raw_detail_json,
                draft.raw_html_path,
                draft.parser_version,
            ),
        )

        conn.commit()
        return int(property_id)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_property(self, property_id: int) -> dict[str, Any] | None:
        """生の properties 行 + 子テーブル行を取得する.

        本番コードからは未使用で、tests (upsert 後の行検証 / calculate_stay_total への
        price_plans 供給) が意図して使用している。get_property_detail
        (store.queries.detail) が契約モデル互換の応答を返すのに対し、本メソッドは
        DB 行の素通しである点が違い。将来 get_property_detail の行取得基盤として
        再利用する可能性を残すため保持するが、共通化リファクタは未実施。
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM properties WHERE id = ?", (property_id,))
            row = cur.fetchone()
            if not row:
                return None
            prop = dict(row)
            prop["price_plans"] = [
                dict(r)
                for r in cur.execute(
                    "SELECT * FROM price_plans WHERE property_id = ? ORDER BY duration_min_days",
                    (property_id,),
                )
            ]
            prop["campaigns"] = [
                dict(r)
                for r in cur.execute(
                    "SELECT * FROM campaigns WHERE property_id = ?",
                    (property_id,),
                )
            ]
            prop["accesses"] = [
                dict(r)
                for r in cur.execute(
                    "SELECT * FROM property_accesses WHERE property_id = ? ORDER BY sort_order",
                    (property_id,),
                )
            ]
            prop["images"] = [
                dict(r)
                for r in cur.execute(
                    "SELECT * FROM property_images WHERE property_id = ? ORDER BY sort_order",
                    (property_id,),
                )
            ]
            prop["features"] = [
                dict(r)
                for r in cur.execute(
                    "SELECT * FROM property_features WHERE property_id = ?",
                    (property_id,),
                )
            ]
            return prop
        finally:
            conn.close()

    def count_by_source(self) -> dict[str, int]:
        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT source_site, COUNT(*) AS n
                FROM properties
                WHERE is_active = 1
                GROUP BY source_site
                """
            )
            return {r["source_site"]: r["n"] for r in rows}
        finally:
            conn.close()

    def counts_by_prefecture(
        self, source_site: str | None = None
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Return {source_site: {pref_slug: {total, active, missing_coords, last_seen_at, last_detail_scraped_at, prefecture_name}}}."""
        conn = self.connect()
        try:
            sql = """
                SELECT source_site,
                       COALESCE(prefecture_slug, '') AS prefecture_slug,
                       MAX(prefecture_name) AS prefecture_name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN is_active = 1 AND (lat IS NULL OR lng IS NULL) THEN 1 ELSE 0 END) AS missing_coords,
                       MAX(last_seen_at) AS last_seen_at,
                       MAX(detail_scraped_at) AS last_detail_scraped_at
                FROM properties
            """
            params: list[Any] = []
            if source_site:
                sql += " WHERE source_site = ?"
                params.append(source_site)
            sql += " GROUP BY source_site, COALESCE(prefecture_slug, '')"
            out: dict[str, dict[str, dict[str, Any]]] = {}
            for row in conn.execute(sql, params):
                sid = row["source_site"]
                slug = row["prefecture_slug"] or ""
                out.setdefault(sid, {})[slug] = {
                    "total": int(row["total"] or 0),
                    "active": int(row["active"] or 0),
                    "missing_coords": int(row["missing_coords"] or 0),
                    "last_seen_at": row["last_seen_at"],
                    "last_detail_scraped_at": row["last_detail_scraped_at"],
                    "prefecture_name": row["prefecture_name"],
                }
            return out
        finally:
            conn.close()

    def fail_stale_running_runs(self) -> int:
        """Close scrape runs/targets left 'running' by a crash or restart.

        スクレイプタスクはプロセス内で直列(タスク入口のロック)のため、起動時や
        新タスク開始時に残っている running 行はプロセス死亡の残骸と確定できる。
        放置すると running_scrape_targets の 12 時間ウィンドウ内は admin UI の
        is_running 表示(ローディング/ハイライト)が消えないままになる。
        Returns the number of aborted run rows.
        """
        now = datetime.now().isoformat()
        summary = "aborted: run interrupted by process restart"
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE scrape_run_targets SET
                    finished_at = ?, status = 'aborted',
                    error_summary = COALESCE(error_summary, ?)
                WHERE finished_at IS NULL AND status = 'running'
                """,
                (now, summary),
            )
            cur.execute(
                """
                UPDATE scrape_runs SET
                    finished_at = ?, status = 'aborted',
                    error_summary = COALESCE(error_summary, ?)
                WHERE finished_at IS NULL AND status = 'running'
                """,
                (now, summary),
            )
            conn.commit()
            return cur.rowcount or 0
        finally:
            conn.close()

    def running_scrape_targets(
        self, source_site: str, *, within_hours: int = 12
    ) -> set[str]:
        """Target keys currently being scraped (run in flight, target unfinished).

        Stale rows left by crashed runs are excluded via the parent-run status
        and a start-time window.
        """
        cutoff = (datetime.now() - timedelta(hours=within_hours)).isoformat()
        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT srt.target_key
                FROM scrape_run_targets srt
                INNER JOIN scrape_runs sr ON sr.id = srt.run_id
                WHERE srt.source_site = ?
                  AND srt.finished_at IS NULL
                  AND sr.status = 'running'
                  AND srt.started_at >= ?
                """,
                (source_site, cutoff),
            )
            return {r["target_key"] for r in rows}
        finally:
            conn.close()

    def latest_scrape_runs_by_target(
        self, source_site: str | None = None
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Latest finished scrape_run_targets per source/target.

        Returns {source_site: {target_key: {finished_at, status, list_items, detail_ok, detail_fail, run_id}}}.
        """
        conn = self.connect()
        try:
            # Prefer finished_at, fall back to started_at for still-running rows
            sql = """
                SELECT srt.id, srt.run_id, srt.source_site, srt.target_key,
                       srt.started_at, srt.finished_at, srt.status,
                       srt.list_pages, srt.list_items, srt.detail_ok, srt.detail_fail,
                       srt.error_summary
                FROM scrape_run_targets srt
                INNER JOIN (
                    SELECT source_site, target_key, MAX(id) AS max_id
                    FROM scrape_run_targets
                    GROUP BY source_site, target_key
                ) latest
                  ON srt.id = latest.max_id
            """
            params: list[Any] = []
            if source_site:
                sql += " WHERE srt.source_site = ?"
                params.append(source_site)
            out: dict[str, dict[str, dict[str, Any]]] = {}
            for row in conn.execute(sql, params):
                sid = row["source_site"]
                key = row["target_key"]
                out.setdefault(sid, {})[key] = {
                    "run_id": row["run_id"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "status": row["status"],
                    "list_pages": row["list_pages"] or 0,
                    "list_items": row["list_items"] or 0,
                    "detail_ok": row["detail_ok"] or 0,
                    "detail_fail": row["detail_fail"] or 0,
                    "error_summary": row["error_summary"],
                    "last_run_at": row["finished_at"] or row["started_at"],
                }
            return out
        finally:
            conn.close()

    def recent_scrape_runs(self, limit: int = 8) -> list[dict[str, Any]]:
        """Recent scrape_runs rows (newest first) for the admin UI.

        Survives process restarts unlike in-memory TASK_STATUS, so the FE can
        show the outcome of e.g. a nightly rotation run after a redeploy.
        """
        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, source_site, started_at, finished_at, status,
                       list_pages, list_items, detail_ok, detail_fail,
                       error_summary
                FROM scrape_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_inactive_missing(
        self,
        source_site: str,
        seen_external_ids: set[str],
        *,
        prefecture_slug: str | None = None,
    ) -> int:
        """Mark properties not in seen set as inactive. Returns rows updated."""
        conn = self.connect()
        try:
            cur = conn.cursor()
            if prefecture_slug:
                cur.execute(
                    """
                    SELECT id, external_id FROM properties
                    WHERE source_site = ? AND prefecture_slug = ? AND is_active = 1
                    """,
                    (source_site, prefecture_slug),
                )
            else:
                cur.execute(
                    """
                    SELECT id, external_id FROM properties
                    WHERE source_site = ? AND is_active = 1
                    """,
                    (source_site,),
                )
            to_deactivate = [r["id"] for r in cur.fetchall() if r["external_id"] not in seen_external_ids]
            for pid in to_deactivate:
                cur.execute(
                    "UPDATE properties SET is_active = 0, last_seen_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), pid),
                )
            conn.commit()
            return len(to_deactivate)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Shortlist
    # ------------------------------------------------------------------

    def update_shortlist(
        self,
        property_id: int,
        status: str,
        comment: str | None = None,
    ) -> None:
        """ショートリスト行を 1 物件分更新する (status が空系/'none' なら行削除).

        物件 id の解決 (external_id / 県間曖昧性) は queries 層の
        resolve_property_id (store.queries._common) の専任とし、本メソッドは
        解決済み properties.id への書込 (DELETE / INSERT..ON CONFLICT + commit)
        のみを担う。queries 側の公開 API は store.queries.detail.update_shortlist。
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            if status in (None, "", "none"):
                cur.execute("DELETE FROM shortlists WHERE property_id = ?", (property_id,))
            else:
                cur.execute(
                    """
                    INSERT INTO shortlists (property_id, status, comment, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(property_id) DO UPDATE SET
                        status = excluded.status,
                        comment = COALESCE(excluded.comment, shortlists.comment),
                        updated_at = excluded.updated_at
                    """,
                    (property_id, status, comment, datetime.now().isoformat()),
                )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Scrape runs
    # ------------------------------------------------------------------

    def start_scrape_run(self, source_site: str, meta: dict | None = None) -> int:
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO scrape_runs (source_site, started_at, status, meta_json)
                VALUES (?, ?, 'running', ?)
                """,
                (source_site, datetime.now().isoformat(), json.dumps(meta or {}, ensure_ascii=False)),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def finish_scrape_run(
        self,
        run_id: int,
        *,
        status: str = "ok",
        list_pages: int = 0,
        list_items: int = 0,
        detail_ok: int = 0,
        detail_fail: int = 0,
        error_summary: str | None = None,
    ) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """
                UPDATE scrape_runs SET
                    finished_at = ?, status = ?, list_pages = ?, list_items = ?,
                    detail_ok = ?, detail_fail = ?, error_summary = ?
                WHERE id = ?
                """,
                (
                    datetime.now().isoformat(),
                    status,
                    list_pages,
                    list_items,
                    detail_ok,
                    detail_fail,
                    error_summary,
                    run_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def start_scrape_run_target(
        self,
        run_id: int,
        source_site: str,
        target_key: str,
    ) -> int:
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO scrape_run_targets
                    (run_id, source_site, target_key, started_at, status)
                VALUES (?, ?, ?, ?, 'running')
                """,
                (run_id, source_site, target_key, datetime.now().isoformat()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def finish_scrape_run_target(
        self,
        target_run_id: int,
        *,
        status: str = "ok",
        list_pages: int = 0,
        list_items: int = 0,
        detail_ok: int = 0,
        detail_fail: int = 0,
        error_summary: str | None = None,
        list_completed: bool = False,
    ) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """
                UPDATE scrape_run_targets SET
                    finished_at = ?, status = ?, list_pages = ?, list_items = ?,
                    detail_ok = ?, detail_fail = ?, error_summary = ?,
                    list_completed = ?
                WHERE id = ?
                """,
                (
                    datetime.now().isoformat(),
                    status,
                    list_pages,
                    list_items,
                    detail_ok,
                    detail_fail,
                    error_summary,
                    1 if list_completed else 0,
                    target_run_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Rotation state
    # ------------------------------------------------------------------

    def upsert_rotation_state(
        self,
        source_site: str,
        prefecture_slug: str,
        *,
        known_total: int | None = None,
        last_full_ok_at: str | None = None,
        last_run_at: str | None = None,
        consecutive_failures: int | None = None,
    ) -> None:
        """Insert or partially update rotation_state row. Non-None fields only on update."""
        conn = self.connect()
        try:
            cur = conn.cursor()
            now = datetime.now().isoformat()
            cur.execute(
                "SELECT 1 FROM rotation_state WHERE source_site = ? AND prefecture_slug = ?",
                (source_site, prefecture_slug),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    INSERT INTO rotation_state
                        (source_site, prefecture_slug, known_total,
                         last_full_ok_at, last_run_at, consecutive_failures, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_site,
                        prefecture_slug,
                        known_total,
                        last_full_ok_at,
                        last_run_at,
                        consecutive_failures,
                        now,
                    ),
                )
            else:
                sets = ["updated_at = ?"]
                params: list[Any] = [now]
                if known_total is not None:
                    sets.append("known_total = ?")
                    params.append(known_total)
                if last_full_ok_at is not None:
                    sets.append("last_full_ok_at = ?")
                    params.append(last_full_ok_at)
                if last_run_at is not None:
                    sets.append("last_run_at = ?")
                    params.append(last_run_at)
                if consecutive_failures is not None:
                    sets.append("consecutive_failures = ?")
                    params.append(consecutive_failures)
                params.extend([source_site, prefecture_slug])
                cur.execute(
                    f"""
                    UPDATE rotation_state SET {', '.join(sets)}
                    WHERE source_site = ? AND prefecture_slug = ?
                    """,
                    tuple(params),
                )
            conn.commit()
        finally:
            conn.close()

    def bump_rotation_failures(
        self,
        source_site: str,
        prefecture_slug: str,
        *,
        last_run_at: str | None = None,
    ) -> None:
        """Record a failed rotation attempt: increment consecutive_failures atomically."""
        now = datetime.now().isoformat()
        last_run_at = last_run_at or now
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT INTO rotation_state
                    (source_site, prefecture_slug, last_run_at, consecutive_failures, updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(source_site, prefecture_slug) DO UPDATE SET
                    consecutive_failures = COALESCE(rotation_state.consecutive_failures, 0) + 1,
                    last_run_at = excluded.last_run_at,
                    updated_at = excluded.updated_at
                """,
                (source_site, prefecture_slug, last_run_at, now),
            )
            conn.commit()
        finally:
            conn.close()

    def load_rotation_states(self, source_site: str) -> list[dict]:
        """Return rotation_state rows for a source, ordered by prefecture_slug."""
        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT prefecture_slug, known_total, last_full_ok_at, last_run_at,
                       consecutive_failures, updated_at
                FROM rotation_state
                WHERE source_site = ?
                ORDER BY prefecture_slug ASC
                """,
                (source_site,),
            )
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def rotation_usage_today(self, source_site: str, now: datetime | None = None) -> int:
        """Sum of detail_ok for rotation-flagged runs started today (local time)."""
        now = now or datetime.now()
        start_of_day = datetime(now.year, now.month, now.day).isoformat()
        conn = self.connect()
        try:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(detail_ok), 0) FROM scrape_runs
                WHERE source_site = ? AND started_at >= ?
                  AND meta_json LIKE '%"rotation": true%'
                """,
                (source_site, start_of_day),
            ).fetchone()
            return int(row[0] or 0)
        finally:
            conn.close()

    def seed_rotation_state(self, source_site: str, pref_catalog: list[str]) -> int:
        """Insert rotation_state rows for prefectures not yet tracked. Returns inserted count."""
        conn = self.connect()
        try:
            cur = conn.cursor()
            now = datetime.now().isoformat()
            inserted = 0
            for slug in pref_catalog:
                cur.execute(
                    "SELECT 1 FROM rotation_state WHERE source_site = ? AND prefecture_slug = ?",
                    (source_site, slug),
                )
                if cur.fetchone() is not None:
                    continue
                cur.execute(
                    """
                    SELECT COUNT(*) FROM properties
                    WHERE source_site = ? AND prefecture_slug = ?
                    """,
                    (source_site, slug),
                )
                known_total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    """
                    INSERT INTO rotation_state
                        (source_site, prefecture_slug, known_total,
                         last_full_ok_at, last_run_at, updated_at)
                    VALUES (?, ?, ?, NULL, NULL, ?)
                    """,
                    (source_site, slug, known_total, now),
                )
                inserted += 1
            conn.commit()
            return inserted
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Admin stats
    # ------------------------------------------------------------------

    def db_stats(self) -> dict[str, Any]:
        """Admin status 用の DB 統計。

        旧 web_server.py の /api/admin/status 直 SQL (properties / shortlists
        の 4 集計) を web 層から Repository へ集約したもの。by_source は既存
        count_by_source() を再利用する。
        Returns {total_properties, missing_coordinates, shortlist, by_source}.
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            total_properties = cur.execute(
                "SELECT COUNT(*) FROM properties WHERE is_active = 1"
            ).fetchone()[0]
            missing_coordinates = cur.execute(
                """
                SELECT COUNT(*) FROM properties
                WHERE is_active = 1 AND (lat IS NULL OR lng IS NULL)
                """
            ).fetchone()[0]
            shortlist_stats: dict[str, int] = {
                row["status"]: row["n"]
                for row in cur.execute(
                    "SELECT status, COUNT(*) AS n FROM shortlists GROUP BY status"
                )
            }
        finally:
            conn.close()
        # by_source は既存メソッドを再利用 (集計条件は同一: is_active = 1)
        return {
            "total_properties": int(total_properties),
            "missing_coordinates": int(missing_coordinates),
            "shortlist": shortlist_stats,
            "by_source": self.count_by_source(),
        }
