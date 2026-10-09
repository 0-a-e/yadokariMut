"""Repository for multi-source property store (PostgreSQL・psycopg3).

SQLite→PG移行 (docs/sqlite-pg-migration-plan.md) により接続の正本は
``store.pg``(DSN は ``YADOKARIMUT_PG_DSN``)。本モジュールは書込系 SQL の
SSOT として残る。プレースホルダは ``%s``(psycopg3)。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import psycopg

from domain.models import PropertyDraft, PropertyImage
from domain.pricing import compute_catalog_min_daily, resolve_plans_effective
from store.building_identity import assign_building
from store.pg import connect as _pg_connect
from store.pg import open_connection

# 従来 ``store.repository`` から import していた呼び出し側のための再輸出
# (新規コードは ``store.pg`` から直接 import してよい)。
get_connection = _pg_connect


def now_iso() -> str:
    """DB タイムスタンプ標準 (naive local ISO8601) の一元生成点。"""
    return datetime.now().isoformat()


class Repository:
    """Thin data access for the property schema. Does not scrape."""

    def connect(self) -> psycopg.Connection:
        """生コネクションを返す (テスト・移行ツール等の自前管理向け)。"""
        return _pg_connect()

    def _conn(self) -> Iterator[psycopg.Connection]:
        """close 保証付き接続(commit/rollback は呼び出し側が明示)。"""
        return open_connection()

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert_property(self, draft: PropertyDraft) -> int:
        """Insert or update a property and replace child rows. Returns property id."""
        with self._conn() as conn:
            return self._upsert_property_conn(conn, draft)

    def _upsert_property_conn(self, conn: psycopg.Connection, draft: PropertyDraft) -> int:
        now = now_iso()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, first_seen_at FROM properties WHERE source_site = %s AND external_id = %s",
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
                source_site, external_id, entity_type, title, detail_url,
                prefecture_slug, prefecture_name, municipality, address,
                lat, lng, geocode_source, geocode_confidence,
                layout, area_m2, area_m2_max, built_year, built_month,
                construction_year_text, capacity_text, structure, floors_text,
                floor_number, floor_number_max, building_floors,
                orientation_text, orientation_deg, orientation_source,
                point_text, availability_text, min_stay_days,
                contract_fee_yen, first_seen_at, last_seen_at, detail_scraped_at,
                is_active, catalog_rent_per_day_yen
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
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
                floor_number_max = excluded.floor_number_max,
                building_floors = excluded.building_floors,
                orientation_text = excluded.orientation_text,
                orientation_deg = excluded.orientation_deg,
                orientation_source = excluded.orientation_source,
                point_text = excluded.point_text,
                availability_text = excluded.availability_text,
                min_stay_days = excluded.min_stay_days,
                contract_fee_yen = excluded.contract_fee_yen,
                last_seen_at = excluded.last_seen_at,
                detail_scraped_at = COALESCE(excluded.detail_scraped_at, properties.detail_scraped_at),
                is_active = excluded.is_active,
                catalog_rent_per_day_yen = excluded.catalog_rent_per_day_yen
                RETURNING id
            """,
            (
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
                draft.floor_number_max,
                draft.building_floors,
                draft.orientation_text,
                draft.orientation_deg,
                draft.orientation_source,
                draft.point_text,
                draft.availability_text,
                draft.min_stay_days,
                draft.contract_fee_yen,
                first_seen_at,
                now,
                draft.detail_scraped_at,
                draft.is_active,
                catalog_daily,
            ),
        )
        if not property_id:
            property_id = cur.fetchone()["id"]

        # Replace children
        cur.execute("DELETE FROM property_accesses WHERE property_id = %s", (property_id,))
        for a in draft.accesses:
            cur.execute(
                """
                INSERT INTO property_accesses
                (property_id, line_name, station_name, walk_minutes, raw_text, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (property_id, a.line_name, a.station_name, a.walk_minutes, a.raw_text, a.sort_order),
            )

        # 差分同期: DELETE→再INSERT だと再スクレイプのたびに media_id/fetch_status
        # 等の取得状態が消えるため、残存URLは行を温存して表示属性のみ更新する。
        seen_urls: set[str] = set()
        draft_images: list[tuple[int, PropertyImage]] = []
        for i, img in enumerate(draft.images):
            if img.image_url in seen_urls:
                continue  # draft 内の URL 重複は最初の出現を採用(UNIQUE と整合)
            seen_urls.add(img.image_url)
            draft_images.append((i, img))  # i は sort_order fallback(従来挙動)

        cur.execute(
            "SELECT id, image_url FROM property_images WHERE property_id = %s",
            (property_id,),
        )
        existing_images = {row["image_url"]: row["id"] for row in cur.fetchall()}

        gone_urls = [url for url in existing_images if url not in seen_urls]
        if gone_urls:
            cur.execute(
                "DELETE FROM property_images"
                " WHERE property_id = %s AND image_url = ANY(%s)",
                (property_id, gone_urls),
            )

        for fallback_order, img in draft_images:
            sort_order = img.sort_order if img.sort_order is not None else fallback_order
            if img.image_url in existing_images:
                cur.execute(
                    """
                    UPDATE property_images
                    SET sort_order = %s, image_type = %s, alt_text = %s, scraped_at = %s
                    WHERE id = %s
                    """,
                    (sort_order, img.image_type, img.alt_text, now,
                     existing_images[img.image_url]),
                )
            else:
                # 新規URL: fetch_status は DEFAULT 'pending'(media_id は NULL)
                cur.execute(
                    """
                    INSERT INTO property_images
                    (property_id, image_url, image_type, alt_text, sort_order, scraped_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (property_id, img.image_url, img.image_type, img.alt_text,
                     sort_order, now),
                )

        cur.execute("DELETE FROM property_links WHERE property_id = %s", (property_id,))
        for link in draft.links:
            cur.execute(
                """
                INSERT INTO property_links
                (property_id, link_type, url, label, scraped_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (property_id, link.link_type, link.url, link.label, now),
            )

        self._replace_features(cur, property_id, draft.features)

        cur.execute("DELETE FROM price_plans WHERE property_id = %s", (property_id,))
        for p in draft.price_plans:
            cur.execute(
                """
                INSERT INTO price_plans (
                    property_id, plan_key, plan_name, duration_min_days, duration_max_days,
                    available, presentation_unit, rent_original_yen, rent_current_yen,
                    management_yen, utilities_yen, utilities_included, cleaning_yen,
                    campaign_label, raw_text, scraped_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    property_id,
                    p.plan_key,
                    p.plan_name,
                    p.duration_min_days,
                    p.duration_max_days,
                    p.available,
                    p.presentation_unit,
                    p.rent_original_yen,
                    p.rent_current_yen,
                    p.management_yen,
                    p.utilities_yen,
                    p.utilities_included,
                    p.cleaning_yen,
                    p.campaign_label,
                    p.raw_text,
                    now,
                ),
            )

        cur.execute("DELETE FROM campaigns WHERE property_id = %s", (property_id,))
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
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                raw_html_path, parser_version
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                property_id,
                now,
                draft.is_active,
                catalog_daily,
                draft.raw_html_path,
                draft.parser_version,
            ),
        )

        # 建物割当(建物集約設計 §5 第 1 段 — 同一トランザクション内の決定的名寄せ。
        # address_key 完全一致のみ・読み取り+building 割当の最小処理)
        assign_building(cur, property_id)

        conn.commit()
        return int(property_id)

    @staticmethod
    def _replace_features(
        cur: psycopg.Cursor, property_id: int, features: list[PropertyFeature]
    ) -> None:
        cur.execute("DELETE FROM property_features WHERE property_id = %s", (property_id,))
        for f in features:
            category = f.category
            if category is None:
                # 旧フィールド名(feature_category)からの移行互換(テスト FIXTURE 等)
                category = getattr(f, "feature_category", None)
            cur.execute(
                """
                INSERT INTO property_features
                (property_id, feature_name, category)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (property_id, f.feature_name, category),
            )

    def replace_features(self, property_id: int, features: list[PropertyFeature]) -> None:
        """features 行を差し替える(再パース等のデータ修正用・単一トランザクション)。"""
        with self._conn() as conn:
            self._replace_features(conn.cursor(), property_id, features)
            conn.commit()

    def update_floors(
        self,
        property_id: int,
        floors_text: str | None,
        floor_number: int | None,
        floor_number_max: int | None,
        building_floors: int | None,
    ) -> None:
        """階数 4 列を差し替える(reparse-floors 等のデータ修正用・単一トランザクション)。"""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE properties
                SET floors_text = %s, floor_number = %s,
                    floor_number_max = %s, building_floors = %s
                WHERE id = %s
                """,
                (floors_text, floor_number, floor_number_max, building_floors, property_id),
            )
            conn.commit()

    def update_orientation(
        self,
        property_id: int,
        orientation_text: str | None,
        orientation_deg: int | None,
        orientation_source: str | None,
    ) -> None:
        """向き 3 列を差し替える(reparse-orientation 等のデータ修正用・単一トランザクション)。"""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE properties
                SET orientation_text = %s, orientation_deg = %s, orientation_source = %s
                WHERE id = %s
                """,
                (orientation_text, orientation_deg, orientation_source, property_id),
            )
            conn.commit()

    def update_point_text(self, property_id: int, point_text: str | None) -> None:
        """紹介文(point_text)を差し替える(reparse-point 等のデータ修正用・単一トランザクション)。"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE properties SET point_text = %s WHERE id = %s",
                (point_text, property_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------


    def count_by_source(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT source_site, COUNT(*) AS n
                FROM properties
                WHERE is_active
                GROUP BY source_site
                """
            )
            return {r["source_site"]: r["n"] for r in rows}

    def counts_by_prefecture(
        self, source_site: str | None = None
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Return {source_site: {pref_slug: {total, active, missing_coords, last_seen_at, last_detail_scraped_at, prefecture_name}}}."""
        with self._conn() as conn:
            sql = """
                SELECT source_site,
                       COALESCE(prefecture_slug, '') AS prefecture_slug,
                       MAX(prefecture_name) AS prefecture_name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN is_active THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN is_active AND (lat IS NULL OR lng IS NULL) THEN 1 ELSE 0 END) AS missing_coords,
                       MAX(last_seen_at) AS last_seen_at,
                       MAX(detail_scraped_at) AS last_detail_scraped_at
                FROM properties
            """
            params: list[Any] = []
            if source_site:
                sql += " WHERE source_site = %s"
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

    def fail_stale_running_runs(self) -> int:
        """Close scrape runs/targets left 'running' by a crash or restart.

        スクレイプタスクはプロセス内で直列(タスク入口のロック)のため、起動時や
        新タスク開始時に残っている running 行はプロセス死亡の残骸と確定できる。
        放置すると running_scrape_targets の 12 時間ウィンドウ内は admin UI の
        is_running 表示(ローディング/ハイライト)が消えないままになる。
        Returns the number of aborted rows (scrape_runs + scrape_run_targets).
        """
        now = now_iso()
        summary = "aborted: run interrupted by process restart"
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE scrape_run_targets SET
                    finished_at = %s, status = 'aborted',
                    error_summary = COALESCE(error_summary, %s)
                WHERE finished_at IS NULL AND status = 'running'
                """,
                (now, summary),
            )
            aborted_targets = cur.rowcount or 0
            cur.execute(
                """
                UPDATE scrape_runs SET
                    finished_at = %s, status = 'aborted',
                    error_summary = COALESCE(error_summary, %s)
                WHERE finished_at IS NULL AND status = 'running'
                """,
                (now, summary),
            )
            aborted_runs = cur.rowcount or 0
            conn.commit()
            return aborted_targets + aborted_runs

    def running_scrape_targets(
        self, source_site: str, *, within_hours: int = 12
    ) -> set[str]:
        """Target keys currently being scraped (run in flight, target unfinished).

        Stale rows left by crashed runs are excluded via the parent-run status
        and a start-time window.
        """
        cutoff = (datetime.now() - timedelta(hours=within_hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT srt.target_key
                FROM scrape_run_targets srt
                INNER JOIN scrape_runs sr ON sr.id = srt.run_id
                WHERE srt.source_site = %s
                  AND srt.finished_at IS NULL
                  AND sr.status = 'running'
                  AND srt.started_at >= %s
                """,
                (source_site, cutoff),
            )
            return {r["target_key"] for r in rows}

    def latest_scrape_runs_by_target(
        self, source_site: str | None = None
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Latest finished scrape_run_targets per source/target.

        Returns {source_site: {target_key: {finished_at, status, list_items, detail_ok, detail_fail, run_id}}}.
        """
        with self._conn() as conn:
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
                sql += " WHERE srt.source_site = %s"
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

    def recent_scrape_runs(self, limit: int = 8) -> list[dict[str, Any]]:
        """Recent scrape_runs rows (newest first) for the admin UI.

        Survives process restarts unlike in-memory TASK_STATUS, so the FE can
        show the outcome of e.g. a nightly rotation run after a redeploy.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, source_site, started_at, finished_at, status,
                       list_pages, list_items, detail_ok, detail_fail,
                       error_summary
                FROM scrape_runs
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_inactive_missing(
        self,
        source_site: str,
        seen_external_ids: set[str],
        *,
        prefecture_slug: str | None = None,
    ) -> int:
        """Mark properties not in seen set as inactive. Returns rows updated."""
        with self._conn() as conn:
            cur = conn.cursor()
            if prefecture_slug:
                cur.execute(
                    """
                    SELECT id, external_id FROM properties
                    WHERE source_site = %s AND prefecture_slug = %s AND is_active
                    """,
                    (source_site, prefecture_slug),
                )
            else:
                cur.execute(
                    """
                    SELECT id, external_id FROM properties
                    WHERE source_site = %s AND is_active
                    """,
                    (source_site,),
                )
            to_deactivate = [r["id"] for r in cur.fetchall() if r["external_id"] not in seen_external_ids]
            for pid in to_deactivate:
                cur.execute(
                    "UPDATE properties SET is_active = FALSE, last_seen_at = %s WHERE id = %s",
                    (now_iso(), pid),
                )
            conn.commit()
            return len(to_deactivate)

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
        with self._conn() as conn:
            cur = conn.cursor()
            if status in (None, "", "none"):
                cur.execute("DELETE FROM property_shortlists WHERE property_id = %s", (property_id,))
            else:
                cur.execute(
                    """
                    INSERT INTO property_shortlists (property_id, status, comment, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(property_id) DO UPDATE SET
                        status = excluded.status,
                        comment = COALESCE(excluded.comment, property_shortlists.comment),
                        updated_at = excluded.updated_at
                    """,
                    (property_id, status, comment, now_iso()),
                )
            conn.commit()

    def update_building_shortlist(
        self,
        building_id: int,
        status: str,
        comment: str | None = None,
    ) -> None:
        """建物ショートリスト行を 1 建物分更新する (status が空系/'none' なら行削除).

        部屋の update_shortlist と対称の同型テーブル。当面 status='saved'(+メモ)
        のみ運用(API 層で検証)。buildings.id の存在検証は queries 層が担う。
        """
        with self._conn() as conn:
            cur = conn.cursor()
            if status in (None, "", "none"):
                cur.execute(
                    "DELETE FROM building_shortlists WHERE building_id = %s",
                    (building_id,),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO building_shortlists
                        (building_id, status, comment, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(building_id) DO UPDATE SET
                        status = excluded.status,
                        comment = COALESCE(excluded.comment, building_shortlists.comment),
                        updated_at = excluded.updated_at
                    """,
                    (building_id, status, comment, now_iso()),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # Scrape runs
    # ------------------------------------------------------------------

    def start_scrape_run(self, source_site: str, meta: dict | None = None) -> int:
        # rotation フラグは Phase 6b から is_rotation 列が正本(meta_json の
        # LIKE 抽出は廃止)。meta から pop して残りを meta_json へ
        meta = dict(meta or {})
        is_rotation = bool(meta.pop("rotation", False))
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO scrape_runs (source_site, started_at, status, meta_json, is_rotation)
                VALUES (%s, %s, 'running', %s, %s)
                RETURNING id
                """,
                (source_site, now_iso(), json.dumps(meta, ensure_ascii=False), is_rotation),
            )
            conn.commit()
            return int(cur.fetchone()["id"])

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
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE scrape_runs SET
                    finished_at = %s, status = %s, list_pages = %s, list_items = %s,
                    detail_ok = %s, detail_fail = %s, error_summary = %s
                WHERE id = %s
                """,
                (
                    now_iso(),
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

    def start_scrape_run_target(
        self,
        run_id: int,
        source_site: str,
        target_key: str,
    ) -> int:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO scrape_run_targets
                    (run_id, source_site, target_key, started_at, status)
                VALUES (%s, %s, %s, %s, 'running')
                RETURNING id
                """,
                (run_id, source_site, target_key, now_iso()),
            )
            conn.commit()
            return int(cur.fetchone()["id"])

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
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE scrape_run_targets SET
                    finished_at = %s, status = %s, list_pages = %s, list_items = %s,
                    detail_ok = %s, detail_fail = %s, error_summary = %s,
                    list_completed = %s
                WHERE id = %s
                """,
                (
                    now_iso(),
                    status,
                    list_pages,
                    list_items,
                    detail_ok,
                    detail_fail,
                    error_summary,
                    list_completed,
                    target_run_id,
                ),
            )
            conn.commit()

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
        with self._conn() as conn:
            cur = conn.cursor()
            now = now_iso()
            cur.execute(
                "SELECT 1 FROM rotation_state WHERE source_site = %s AND prefecture_slug = %s",
                (source_site, prefecture_slug),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    INSERT INTO rotation_state
                        (source_site, prefecture_slug, known_total,
                         last_full_ok_at, last_run_at, consecutive_failures, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
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
                sets = ["updated_at = %s"]
                params: list[Any] = [now]
                if known_total is not None:
                    sets.append("known_total = %s")
                    params.append(known_total)
                if last_full_ok_at is not None:
                    sets.append("last_full_ok_at = %s")
                    params.append(last_full_ok_at)
                if last_run_at is not None:
                    sets.append("last_run_at = %s")
                    params.append(last_run_at)
                if consecutive_failures is not None:
                    sets.append("consecutive_failures = %s")
                    params.append(consecutive_failures)
                params.extend([source_site, prefecture_slug])
                cur.execute(
                    f"""
                    UPDATE rotation_state SET {', '.join(sets)}
                    WHERE source_site = %s AND prefecture_slug = %s
                    """,
                    tuple(params),
                )
            conn.commit()

    def bump_rotation_failures(
        self,
        source_site: str,
        prefecture_slug: str,
        *,
        last_run_at: str | None = None,
    ) -> None:
        """Record a failed rotation attempt: increment consecutive_failures atomically."""
        now = now_iso()
        last_run_at = last_run_at or now
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO rotation_state
                    (source_site, prefecture_slug, last_run_at, consecutive_failures, updated_at)
                VALUES (%s, %s, %s, 1, %s)
                ON CONFLICT(source_site, prefecture_slug) DO UPDATE SET
                    consecutive_failures = COALESCE(rotation_state.consecutive_failures, 0) + 1,
                    last_run_at = excluded.last_run_at,
                    updated_at = excluded.updated_at
                """,
                (source_site, prefecture_slug, last_run_at, now),
            )
            conn.commit()

    def load_rotation_states(self, source_site: str) -> list[dict]:
        """Return rotation_state rows for a source, ordered by prefecture_slug."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT prefecture_slug, known_total, last_full_ok_at, last_run_at,
                       consecutive_failures, updated_at
                FROM rotation_state
                WHERE source_site = %s
                ORDER BY prefecture_slug ASC
                """,
                (source_site,),
            )
            return [dict(r) for r in rows]

    def rotation_usage_today(self, source_site: str, now: datetime | None = None) -> int:
        """Sum of detail_ok for rotation-flagged runs started today (local time)."""
        now = now or datetime.now()
        start_of_day = datetime(now.year, now.month, now.day).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(detail_ok), 0) AS n FROM scrape_runs
                WHERE source_site = %s AND started_at >= %s AND is_rotation
                """,
                (source_site, start_of_day),
            ).fetchone()
            return int(row["n"] or 0)

    def seed_rotation_state(self, source_site: str, pref_catalog: list[str]) -> int:
        """Insert rotation_state rows for prefectures not yet tracked. Returns inserted count."""
        with self._conn() as conn:
            cur = conn.cursor()
            now = now_iso()
            inserted = 0
            for slug in pref_catalog:
                cur.execute(
                    "SELECT 1 FROM rotation_state WHERE source_site = %s AND prefecture_slug = %s",
                    (source_site, slug),
                )
                if cur.fetchone() is not None:
                    continue
                cur.execute(
                    """
                    SELECT COUNT(*) AS n FROM properties
                    WHERE source_site = %s AND prefecture_slug = %s
                    """,
                    (source_site, slug),
                )
                known_total = int(cur.fetchone()["n"] or 0)
                cur.execute(
                    """
                    INSERT INTO rotation_state
                        (source_site, prefecture_slug, known_total,
                         last_full_ok_at, last_run_at, updated_at)
                    VALUES (%s, %s, %s, NULL, NULL, %s)
                    """,
                    (source_site, slug, known_total, now),
                )
                inserted += 1
            conn.commit()
            return inserted

    # ------------------------------------------------------------------
    # Admin stats
    # ------------------------------------------------------------------

    def db_stats(self) -> dict[str, Any]:
        """Admin status 用の DB 統計。

        旧 web_server.py の /api/admin/status 直 SQL (properties / property_shortlists
        の 4 集計) を web 層から Repository へ集約したもの。by_source は既存
        count_by_source() を再利用する。
        Returns {total_properties, missing_coordinates, shortlist, by_source}.
        """
        with self._conn() as conn:
            cur = conn.cursor()
            total_properties = cur.execute(
                "SELECT COUNT(*) AS n FROM properties WHERE is_active"
            ).fetchone()["n"]
            missing_coordinates = cur.execute(
                """
                SELECT COUNT(*) AS n FROM properties
                WHERE is_active AND (lat IS NULL OR lng IS NULL)
                """
            ).fetchone()["n"]
            shortlist_stats: dict[str, int] = {
                row["status"]: row["n"]
                for row in cur.execute(
                    "SELECT status, COUNT(*) AS n FROM property_shortlists GROUP BY status"
                )
            }
            building_shortlist_stats: dict[str, int] = {
                row["status"]: row["n"]
                for row in cur.execute(
                    "SELECT status, COUNT(*) AS n FROM building_shortlists GROUP BY status"
                )
            }

        # by_source は既存メソッドを再利用 (集計条件は同一: is_active)
        return {
            "total_properties": int(total_properties),
            "missing_coordinates": int(missing_coordinates),
            "shortlist": shortlist_stats,
            "building_shortlist": building_shortlist_stats,
            "by_source": self.count_by_source(),
        }
