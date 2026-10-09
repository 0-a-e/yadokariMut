import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import argparse


def cmd_db_init(args):
    """Apply PostgreSQL schema via Alembic (upgrade head)."""
    from store.migrations import upgrade_head

    upgrade_head()
    print("PostgreSQL schema applied (alembic upgrade head).")


def cmd_scrape(args):
    """Multi-source v2 scrape (SourceAdapter + Repository)."""
    from ingest.pipeline import IngestPipeline
    from ingest.source_config import resolve_source_adapter_config
    from sources.registry import SourceRegistry
    from store.repository import Repository

    source_id = args.source
    src_cfg = resolve_source_adapter_config(
        source_id, pref_filter=args.pref, delay=args.delay
    )

    repo = Repository()

    adapter = SourceRegistry.create(source_id, src_cfg)
    pipeline = IngestPipeline(adapter, repo, save_raw=not args.no_raw)

    if args.fixture_detail:
        with open(args.fixture_detail, "r", encoding="utf-8") as f:
            html = f.read()
        pid = pipeline.ingest_detail_html(
            html,
            detail_url=args.detail_url or "",
            external_id=args.external_id or "",
            prefecture_slug=(args.pref[0] if args.pref else None),
        )
        print(f"Upserted property id={pid} from fixture")
        return

    max_pages = None if args.all_pages else args.pages
    result = pipeline.run(
        max_pages=max_pages,
        list_only=args.list_only,
        max_details=args.max_details,
        mark_inactive=args.mark_inactive,
    )
    print(
        f"[{result.source_site}] list_pages={result.list_pages} "
        f"list_items={result.list_items} detail_ok={result.detail_ok} "
        f"detail_fail={result.detail_fail} errors={len(result.errors)}"
    )
    if result.errors:
        for e in result.errors[:10]:
            print(f"  - {e}", file=sys.stderr)


def cmd_export_map(args):

    """
    Exports search results to GeoJSON/KML.
    """
    from store.api_queries import export_building_geojson, export_kml

    import api_models

    # params dict の組立正本は api_models.SearchFilters (H2)。
    # required_features は旧実装の strip 無し split を廃止し、生 CSV 文字列を
    # queries 層 (iter_search_properties 冒頭) の正本正規化に委ねる。
    # falsy 値 (未指定 / 0) は None 扱いで除外 = 旧 if 文と同一挙動。
    params = api_models.SearchFilters(
        prefecture_name=args.prefecture or None,
        max_monthly_total_yen=args.max_rent or None,
        min_area_m2=args.min_area or None,
        required_features=args.features,
    ).to_query_params()

    if args.format == "geojson":
        res = export_building_geojson(params, args.out)
    else:
        res = export_kml(params, args.out)

    print(f"Export successful: {res['status']}")
    print(f"File saved to: {res['file_path']}")
    if "feature_count" in res:
        print(f"Features: {res['feature_count']}")
    if "placemark_count" in res:
        print(f"Placemarks: {res['placemark_count']}")


def cmd_geocode(args):
    """
    Geocodes v2 properties missing lat/lng coordinates in the database.
    """
    from store.geocode_v2 import (
        format_geocode_warnings,
        geocode_missing_v2,
        geocode_result_warnings,
    )

    print("Running batch geocoding (v2)...")
    stats = geocode_missing_v2(
        limit=args.limit,
        provider=args.provider,
        force=args.force,
        retry_only=args.retry_only,
    )
    print(
        f"Processed: {stats.get('processed', 0)}, Success: {stats.get('success', 0)}, "
        f"Failed: {stats.get('failed', 0)}, Skipped: {stats.get('skipped', 0)}, "
        f"Unchanged: {stats.get('unchanged', 0)}, Remaining: {stats.get('remaining', 0)}"
    )
    # 警告文言は geocode_v2 の正本 formatter から生成 (spec §3.5/§3.8)
    for line in format_geocode_warnings(geocode_result_warnings(stats)):
        print(line)


def cmd_report_unmapped_features(args):
    """未分類 feature_name の差分検知+語彙品質検出(機能カテゴリ辞書・設計 §5-1)。

    母集団 = 全実値 − NON_FILTER(ignore) セット。突合は両辺正規化(§7-7)。
    あわせて (a) ソース内被覆率 ≥99% の語彙(テンプレ・全物件一律の機械検出)
    (b) mutually exclusive な語の同居(データ品質監視)を報告する。
    日次ジョブとして実行する(設計 §4.1・運用 SLA は §5-1)。
    """
    from domain.feature_categories import is_non_filter, lookup_feature_category
    from store.pg import open_connection

    # mutually exclusive な語彙ペア(§1.4 の矛盾同居の継続監視。検出専用の運用辞書)
    exclusive_pairs = (
        ("3点ユニットバス", "バストイレ別"),
        ("3点ユニットバス", "浴室トイレセパレート"),
        ("3点ユニットバス", "セパレート"),
        ("２点ユニット（バス・トイレ）", "バストイレ別"),
        ("室外洗濯機", "室内洗濯機"),
    )

    with open_connection() as conn:
        rows = conn.execute(
            "SELECT feature_name, COUNT(DISTINCT property_id) AS props "
            "FROM property_features GROUP BY feature_name ORDER BY props DESC"
        ).fetchall()

    unmapped = []
    ignored = 0
    for name, props in rows:
        if is_non_filter(name):
            ignored += 1
        elif lookup_feature_category(name) is None:
            unmapped.append((name, props))

    print(
        f"vocabularies: {len(rows)} "
        f"(mapped: {len(rows) - len(unmapped) - ignored}, "
        f"non_filter: {ignored}, unmapped: {len(unmapped)})"
    )
    for name, props in unmapped:
        print(f"  - {name} ({props:,} properties)")
    if unmapped and args.strict:
        sys.exit(1)

    with open_connection() as conn:
        # (a) ソース内被覆率 ≥99% の語彙(§5-1 b — テンプレ・全物件一律語彙の検出)
        source_totals = {
            r["source_site"]: r["n"]
            for r in conn.execute(
                "SELECT source_site, COUNT(*) AS n FROM properties GROUP BY source_site"
            )
        }
        high_cov = [
            (r["name"], r["site"], r["props"], source_totals.get(r["site"], 0))
            for r in conn.execute(
                "SELECT p.source_site AS site, pf.feature_name AS name, "
                "COUNT(DISTINCT p.id) AS props "
                "FROM property_features pf JOIN properties p ON p.id = pf.property_id "
                "GROUP BY p.source_site, pf.feature_name"
            )
            if source_totals.get(r["site"], 0)
            and r["props"] / source_totals[r["site"]] >= 0.99
        ]
        # (b) mutually exclusive ペアの同居物件数(§5-1 c)
        cooccurrence = []
        for a, b in exclusive_pairs:
            n = conn.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT property_id FROM property_features WHERE feature_name IN (%s, %s) "
                "  GROUP BY property_id HAVING COUNT(DISTINCT feature_name) = 2)",
                (a, b),
            ).fetchone()[0]
            if n:
                cooccurrence.append((a, b, n))

    print(f"high-coverage vocabularies (>=99% of source, template suspects): {len(high_cov)}")
    for name, site, props, total in sorted(high_cov, key=lambda x: -x[2])[:20]:
        print(f"  - {name} [{site}] {props:,}/{total:,}")
    print(f"mutually-exclusive cooccurrences: {len(cooccurrence)}")
    for a, b, n in cooccurrence:
        print(f"  - {a} × {b}: {n:,} properties")


def _latest_detail_targets(source: str, limit: int | None) -> list[tuple[int, str]]:
    """properties ⋈ raw_pages(detail) から物件ごとの最新 detail HTML パスを確定する。

    reparse-features / reparse-floors / reparse-orientation 共通の走査ヘルパ
    (docs/orientation-model-plan.md E3)。fetched_at 昇順で上書きするため各物件の
    最新 detail が残る。返り値は (property_id, storage_path) の property_id 順リスト。
    """
    from store.pg import open_connection

    with open_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id AS pid, rp.storage_path, rp.fetched_at
            FROM properties p
            JOIN raw_pages rp ON rp.url = p.detail_url AND rp.page_type = 'detail'
            WHERE p.source_site = %s
            ORDER BY rp.fetched_at
            """,
            (source,),
        ).fetchall()

    latest: dict[int, str] = {}
    for r in rows:
        latest[r["pid"]] = r["storage_path"]
    targets = sorted(latest.items())
    if limit:
        targets = targets[:limit]
    return targets


def _resolve_storage_path(storage_path: str, storage_root: str | None) -> str:
    """--storage-root 指定時は basename 寄せで解決する(raw 配置が異なる環境向け)。"""
    if storage_root:
        return os.path.join(storage_root, os.path.basename(storage_path))
    return storage_path


def cmd_reparse_features(args):
    """保存済み raw HTML から features を再パースして置き換える。

    unionmonthly facility_list の -active 修正(2026-10-08・設計 §7-4)を過去行へ
    反映する。対象は raw_pages に detail HTML がある物件(各物件の最新 detail を使用)。
    """
    from collections import Counter

    from bs4 import BeautifulSoup
    from sources.unionmonthly.detail_parser import _parse_features
    from store.pg import open_connection
    from store.repository import Repository

    targets = _latest_detail_targets(args.source, args.limit)

    repo = Repository()
    ok = missing = failed = 0
    removed = inserted = 0
    vocab_after: Counter[str] = Counter()
    for i, (pid, storage_path) in enumerate(targets, 1):
        path = _resolve_storage_path(storage_path, args.storage_root)
        if not os.path.exists(path):
            missing += 1
            continue
        try:
            html = open(path, encoding="utf-8", errors="replace").read()
            feats = _parse_features(BeautifulSoup(html, "html.parser"))
        except Exception as e:  # noqa: BLE001 - 1 物件の失敗で全体を止めない
            failed += 1
            print(f"  ! parse failed property_id={pid}: {e}", file=sys.stderr)
            continue
        with open_connection() as conn:
            old_names = [
                r["feature_name"]
                for r in conn.execute(
                    "SELECT feature_name FROM property_features WHERE property_id = %s",
                    (pid,),
                )
            ]
        removed += len(old_names)
        inserted += len(feats)
        for f in feats:
            vocab_after[f.feature_name] += 1
        if not args.dry_run:
            repo.replace_features(pid, feats)
        ok += 1
        if i % 500 == 0:
            print(f"  ... {i}/{len(targets)} properties processed")

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"[{mode}] source={args.source} target={len(targets)} ok={ok} missing={missing} failed={failed}")
    print(f"features rows: {removed:,} -> {inserted:,} (delta {inserted - removed:+,})")
    print("top vocabularies after reparse (properties):")
    for name, cnt in vocab_after.most_common(10):
        print(f"  - {name}: {cnt:,}")


def cmd_reparse_floors(args):
    """保存済み raw HTML から階数を再パースし properties の階数 4 列へ反映する。

    floor_number 整数化(docs/floor-number-ssot-plan.md)を既存行へ遡及適用する。
    対象は raw_pages に detail HTML がある物件(各物件の最新 detail を使用)。
    --source 未指定時は bratto / unionmonthly の両方を処理する。
    """
    import re

    from sources.parsing import parse_floor_text
    from store.repository import Repository

    # 階数セル抽出の正規表現(bratto 規格表「階建」/ unionmonthly 情報表「所在階」)。
    # 対象は過去スナップショットの不変 HTML のため bs4 全パースより高速な正規表現経路を
    # 使う。2026-10-08 PoC で両サイト各 600 件の bs4 参照実装(現行パーサ相当)と
    # 不一致 0 を確認済み(poc/floor_extraction/)。
    bratto_kaidate_re = re.compile(
        r"<th>\s*(?:<h3>)?\s*階建\s*(?:</h3>)?\s*</th>\s*<td[^>]*>(.*?)</td>", re.S
    )
    union_rows_re = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S)
    tag_re = re.compile(r"<[^>]+>")

    def _text(fragment: str) -> str:
        return " ".join(tag_re.sub("", fragment).split())

    def _extract_floor_raw(site: str, html: str) -> str | None:
        if site == "bratto":
            m = bratto_kaidate_re.search(html)
            return _text(m.group(1)) if m else None
        for m in union_rows_re.finditer(html):
            if _text(m.group(1)) == "所在階":
                return _text(m.group(2))
        return None

    sites = ["bratto", "unionmonthly"] if not args.source else [args.source]
    repo = Repository()

    for site in sites:
        targets = _latest_detail_targets(site, args.limit)

        ok = missing = failed = 0
        floor_filled = building_filled = multi = unmatched = 0
        unmatched_samples: list[str] = []
        for i, (pid, storage_path) in enumerate(targets, 1):
            path = _resolve_storage_path(storage_path, args.storage_root)
            if not os.path.exists(path):
                missing += 1
                continue
            try:
                html = open(path, encoding="utf-8", errors="replace").read()
                raw = _extract_floor_raw(site, html)
                spec = parse_floor_text(raw)
            except Exception as e:  # noqa: BLE001 - 1 物件の失敗で全体を止めない
                failed += 1
                print(f"  ! parse failed property_id={pid}: {e}", file=sys.stderr)
                continue
            if raw is not None and spec.floor_min is None and spec.building_floors is None:
                unmatched += 1
                if len(unmatched_samples) < 10:
                    unmatched_samples.append(raw)
            if spec.floor_min is not None:
                floor_filled += 1
            if spec.multi_floor:
                multi += 1
            if spec.building_floors is not None:
                building_filled += 1
            if not args.dry_run:
                repo.update_floors(
                    pid, raw, spec.floor_min, spec.floor_max, spec.building_floors
                )
            ok += 1
            if i % 2000 == 0:
                print(f"  ... {i}/{len(targets)} properties processed")

        mode = "DRY-RUN" if args.dry_run else "APPLIED"
        print(
            f"[{mode}] source={site} target={len(targets)} ok={ok} "
            f"missing={missing} failed={failed}"
        )
        print(
            f"  floor_number filled: {floor_filled} (multi {multi}) / "
            f"building_floors filled: {building_filled} / unmatched: {unmatched}"
        )
        for sample in unmatched_samples:
            print(f"  unmatched sample: [{sample}]")


def cmd_reparse_orientation(args):
    """保存済み raw HTML から向きを再パースし properties の向き 3 列へ反映する。

    角度モデル導入(docs/orientation-model-plan.md)を既存行へ遡及適用する。
    対象は raw_pages に detail HTML がある物件(各物件の最新 detail を使用)。
    bratto はサイト側が向きを非公開のため実行対象は unionmonthly のみ
    (--source 未指定時の既定。bratto に実行しても全件 NULL が期待値)。
    """
    import re
    from collections import Counter

    from sources.parsing import parse_orientation_text
    from store.repository import Repository

    # 向きセル抽出の正規表現(unionmonthly 情報表「向き」。2th+2td 行の後半ペア)。
    # 過去スナップショットの不変 HTML に対する正規表現経路は reparse-floors と同じ
    # 根拠(PoC で全 54,751 ページに <th>向き</th> が存在)。
    muki_re = re.compile(r"<th[^>]*>\s*向き\s*</th>\s*<td[^>]*>(.*?)</td>", re.S)
    tag_re = re.compile(r"<[^>]+>")

    source = args.source or "unionmonthly"
    repo = Repository()
    targets = _latest_detail_targets(source, args.limit)

    ok = missing = failed = 0
    filled = 0
    label_dist: Counter[str] = Counter()
    unmatched: list[str] = []
    for i, (pid, storage_path) in enumerate(targets, 1):
        path = _resolve_storage_path(storage_path, args.storage_root)
        if not os.path.exists(path):
            missing += 1
            continue
        try:
            html = open(path, encoding="utf-8", errors="replace").read()
            m = muki_re.search(html)
            raw = " ".join(tag_re.sub("", m.group(1)).split()) if m else None
            spec = parse_orientation_text(raw)
        except Exception as e:  # noqa: BLE001 - 1 物件の失敗で全体を止めない
            failed += 1
            print(f"  ! parse failed property_id={pid}: {e}", file=sys.stderr)
            continue
        if raw is not None and spec.deg is None:
            if len(unmatched) < 10:
                unmatched.append(raw)
        if spec.deg is not None:
            filled += 1
            label_dist[spec.label or "?"] += 1
        if not args.dry_run:
            # パーサ組込と同一規則: deg が取れたときのみ text/source を設定
            repo.update_orientation(
                pid,
                raw if spec.deg is not None else None,
                spec.deg,
                "spec_parse" if spec.deg is not None else None,
            )
        ok += 1
        if i % 2000 == 0:
            print(f"  ... {i}/{len(targets)} properties processed")

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(
        f"[{mode}] source={source} target={len(targets)} ok={ok} "
        f"missing={missing} failed={failed}"
    )
    print(f"  orientation_deg filled: {filled} / unmatched: {len(unmatched)}")
    print("  label distribution:")
    for label, cnt in label_dist.most_common():
        print(f"    - {label}: {cnt:,}")
    for sample in unmatched:
        print(f"  unmatched sample: [{sample}]")


def cmd_reparse_point(args):
    """保存済み raw HTML からスタッフのおすすめコメントを再パースし point_text へ反映する。

    unionmonthly スタッフコメント抽出(2026-10-09・パーサ unionmonthly-detail-1.3)を
    既存行へ遡及適用する。対象は raw_pages に detail HTML がある物件
    (各物件の最新 detail を使用)。bratto は取り込み時に point_text を解決済みのため
    対象外(--source 既定は unionmonthly)。抽出規則はパーサ組込と同一の
    _parse_point_text を用いる(先頭ボイラープレートのみ除去・見出し無しは全文)。
    """
    from bs4 import BeautifulSoup

    from sources.unionmonthly.detail_parser import _parse_point_text
    from store.repository import Repository

    repo = Repository()
    targets = _latest_detail_targets(args.source, args.limit)

    ok = missing = failed = 0
    filled = blank = 0
    lens: list[int] = []
    for i, (pid, storage_path) in enumerate(targets, 1):
        path = _resolve_storage_path(storage_path, args.storage_root)
        if not os.path.exists(path):
            missing += 1
            continue
        try:
            html = open(path, encoding="utf-8", errors="replace").read()
            point_text = _parse_point_text(BeautifulSoup(html, "html.parser"))
        except Exception as e:  # noqa: BLE001 - 1 物件の失敗で全体を止めない
            failed += 1
            print(f"  ! parse failed property_id={pid}: {e}", file=sys.stderr)
            continue
        if point_text:
            filled += 1
            lens.append(len(point_text))
        else:
            blank += 1
        if not args.dry_run:
            repo.update_point_text(pid, point_text)
        ok += 1
        if i % 2000 == 0:
            print(f"  ... {i}/{len(targets)} properties processed")

    lens.sort()
    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(
        f"[{mode}] source={args.source} target={len(targets)} ok={ok} "
        f"missing={missing} failed={failed}"
    )
    p50 = lens[len(lens) // 2] if lens else 0
    print(
        f"  point_text filled: {filled:,} (p50 {p50:,} / max {lens[-1] if lens else 0:,} chars)"
        f" / blank: {blank:,}"
    )


def cmd_building_identity(args):
    """建物名寄せバッチ(dry-run レポート / 適用)。

    docs/building-aggregation-design.md §5 第 2 段。dry-run は書き込みゼロで
    レポート(建物数・割当率・コンフリクト・クロスソース)を出力する。Phase B1
    の必須成果物(初回はレポートを人手確認してから --apply)。
    """
    import json

    from store.building_identity import run_identity_batch
    from store.pg import open_connection

    with open_connection() as conn:
        report = run_identity_batch(conn, apply=args.apply)

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"[{mode}] building identity report:")
    print(
        f"  properties: {report['total_properties']:,} total /"
        f" {report['grouped_properties']:,} address-keyed"
        f" ({len(report['unassigned'])} unassigned)"
    )
    print(
        f"  buildings: {report['buildings_existing']:,} existing /"
        f" {report['buildings_to_create']:,} to create"
        f" / {report['building_groups']:,} groups"
    )
    print(f"  reassignments: {len(report['moves']):,}")
    if args.apply:
        print(
            f"  after: buildings={report['buildings_after']:,}"
            f" assigned_properties={report['assigned_properties']:,}"
            f" removed_empty={report.get('buildings_removed_empty', 0):,}"
        )
    print(f"  cross-source buildings: {len(report['cross_source_buildings'])}")
    print(f"  name conflicts (same-source >1 name): {len(report['name_conflicts'])}")
    print(f"  coord conflicts (>1 distinct coords): {len(report['coord_conflicts'])}")
    print(f"  attribute conflicts: {len(report['attr_conflicts'])}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def cmd_building_merge(args):
    """building_b を building_a へ統合する(手動オーバーライド・§5)。"""
    from store.building_identity import merge_buildings
    from store.pg import open_connection

    with open_connection() as conn:
        moved = merge_buildings(conn, args.building_a, args.building_b)
    print(f"merged building {args.building_b} -> {args.building_a} (rooms: {moved})")


def cmd_building_split(args):
    """指定部屋を別建物へ分割する(同一住所 2 棟等の手動対処・§10)。"""
    from store.building_identity import split_building
    from store.pg import open_connection

    property_ids = [int(x) for x in args.property_ids.split(",") if x.strip()]
    with open_connection() as conn:
        new_id = split_building(conn, args.building_id, property_ids)
    print(f"split building {args.building_id} -> new building {new_id}")


def cmd_backfill_embeddings(args):
    """意味検索 embedding のバッチ生成(PG移行 Phase 7a・docs/embedding-batch-api-plan.md)。

    既定は Gemini Batch API 経路(asyncBatchEmbedContent・D5): 未完了ジョブの適用 →
    pending の submit → bounded 待機(--wait-secs) → 完了分適用。未完了分は Gemini 側
    ジョブが保持され、翌日の日次ジョブ / 本 CLI 再実行の冒頭で適用される。
    --mode sync はシリアル 1 件 1 呼びのフォールバック(大量 pending ではレート制限
    に接触するため小件の即時修正向け)。--dry-run は API 呼びなしの計上のみ。
    """
    if args.dry_run:
        from store.embeddings import backfill_embeddings

        stats = backfill_embeddings(limit=args.limit, dry_run=True, progress_every=500)
        print(
            f"[DRY-RUN] candidates={stats['candidates']} pending={stats['pending']}"
            f" embedded={stats['embedded']}"
            f" skipped_unchanged={stats['skipped_unchanged']}"
            f" failed={stats['failed']}"
        )
        return 0

    if args.mode == "sync":
        from store.embeddings import backfill_embeddings

        stats = backfill_embeddings(limit=args.limit, progress_every=500)
        print(
            f"[APPLIED] candidates={stats['candidates']} pending={stats['pending']}"
            f" embedded={stats['embedded']}"
            f" skipped_unchanged={stats['skipped_unchanged']}"
            f" failed={stats['failed']}"
        )
        if stats["failed"]:
            print(f"  {stats['failed']} property(ies) failed", file=sys.stderr)
            return 1
        return 0

    from store.embeddings_batch import run_batch_sync

    stats = run_batch_sync(
        limit=args.limit,
        wait_secs=args.wait_secs,
        max_requests_per_batch=args.batch_size,
        submit_only=args.submit_only,
        progress_every=500,
    )
    print(
        f"[BATCH] candidates={stats['candidates']} pending={stats['pending']}"
        f" submitted_batches={stats['submitted_batches']}"
        f" submitted_requests={stats['submitted_requests']}"
        f" applied={stats['applied']}"
        f" stale_skipped={stats['stale_skipped']}"
        f" failed_rows={stats['failed_rows']}"
        f" missing={stats['missing']}"
        f" still_running={stats['outstanding_still_running']}"
    )
    if stats["failed_rows"]:
        print(
            f"  {stats['failed_rows']} result row(s) failed (retried in a later cycle)",
            file=sys.stderr,
        )
    if stats["outstanding_still_running"]:
        print(
            f"  {stats['outstanding_still_running']} batch job(s) still running;"
            " re-run this command or wait for the daily job to apply results"
        )
    return 0


def cmd_media_backfill(args):
    """メディア画像のバッチ取り込み(rustfs・docs/media-storage-rustfs-plan.md M1-β)。

    property_images の pending(/--retry-failed で failed 含む)行を取得して
    クラスタ代表ストアへ格納する(backfill-embeddings と同じ dry-run 慣習)。
    YADOKARIMUT_RUSTFS_* が未設定なら disabled として終了コード 1。
    """
    from store.media import backfill_media

    stats = backfill_media(
        limit=args.limit,
        dry_run=args.dry_run,
        source=args.source,
        retry_failed=args.retry_failed,
        progress_every=500,
    )
    prefix = "[DRY-RUN]" if args.dry_run else "[APPLIED]"
    if stats.get("disabled"):
        print(f"{prefix} media storage disabled (YADOKARIMUT_RUSTFS_* env unset)")
        return 1
    print(f"{prefix} " + " ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Yadokari Monthly Mansion Search System CLI")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # db-init
    parser_db = subparsers.add_parser("db-init", help="Apply PostgreSQL schema via Alembic (upgrade head)")

    # scrape
    parser_scrape = subparsers.add_parser("scrape", help="Multi-source v2 scrape via SourceAdapter")
    parser_scrape.add_argument("--source", type=str, default="unionmonthly", help="Source id (e.g. unionmonthly)")
    parser_scrape.add_argument("--pref", nargs="+", metavar="SLUG", help="Prefecture slug filter (e.g. tokyo)")
    parser_scrape.add_argument("--pages", type=int, default=1, help="Max list pages per pref (ignored with --all-pages)")
    parser_scrape.add_argument("--all-pages", action="store_true", help="Crawl all list pages")
    parser_scrape.add_argument("--list-only", action="store_true", help="Only collect list cards (no detail)")
    parser_scrape.add_argument("--max-details", type=int, help="Cap number of detail pages")
    parser_scrape.add_argument("--delay", type=float, help="Override delay_seconds")
    parser_scrape.add_argument("--mark-inactive", action="store_true", help="Deactivate IDs not seen in this run")
    parser_scrape.add_argument("--no-raw", action="store_true", help="Do not save raw HTML")
    parser_scrape.add_argument("--fixture-detail", type=str, help="Parse offline detail HTML fixture and upsert")
    parser_scrape.add_argument("--detail-url", type=str, help="Detail URL metadata for fixture")
    parser_scrape.add_argument("--external-id", type=str, help="External id override for fixture")

    # export-map
    parser_export = subparsers.add_parser("export-map", help="Export property search results to map format")
    parser_export.add_argument("--format", type=str, choices=["geojson", "kml"], default="geojson", help="Output map format")
    parser_export.add_argument("--out", type=str, help="Custom output file path")
    parser_export.add_argument("--prefecture", type=str, help="Prefecture name filter (e.g. '東京都')")
    parser_export.add_argument("--max-rent", type=int, help="Cheapest monthly total limit in yen")
    parser_export.add_argument("--min-area", type=float, help="Minimum floor area size in m2")
    parser_export.add_argument("--features", type=str, help="Comma-separated list of required features")

    # run-mcp
    subparsers.add_parser("run-mcp", help="Start the stdio MCP server")

    # geocode
    parser_geocode = subparsers.add_parser("geocode", help="Batch geocode v2 properties with missing coordinates")
    parser_geocode.add_argument("--limit", type=int, help="Limit number of properties to geocode in this batch")
    parser_geocode.add_argument("--force", action="store_true", help="Re-geocode all properties even if they already have coordinates")
    parser_geocode.add_argument("--provider", type=str, choices=["nominatim", "google"], help="Explicitly specify the geocoding provider")
    parser_geocode.add_argument("--retry-only", action="store_true", help="Retry only properties that already have a geocode_source (resolved or failed)")

    # report-unmapped-features
    parser_unmapped = subparsers.add_parser(
        "report-unmapped-features",
        help="Report feature_names not covered by the category dictionary (design §5-1)",
    )
    parser_unmapped.add_argument("--strict", action="store_true", help="Exit with code 1 when unmapped vocabularies exist")

    # reparse-features
    parser_reparse = subparsers.add_parser(
        "reparse-features",
        help="Reparse features from saved raw HTML (design §7-4 facility_list -active fix)",
    )
    parser_reparse.add_argument("--source", type=str, default="unionmonthly", help="Source site id to reparse")
    parser_reparse.add_argument("--storage-root", type=str, help="Directory containing raw HTML files (matched by basename; default: use storage_path as-is)")
    parser_reparse.add_argument("--limit", type=int, help="Process only first N properties (testing)")
    parser_reparse.add_argument("--dry-run", action="store_true", help="Report the diff without writing")

    # reparse-floors
    parser_floors = subparsers.add_parser(
        "reparse-floors",
        help="Reparse floor numbers from saved raw HTML (docs/floor-number-ssot-plan.md)",
    )
    parser_floors.add_argument("--source", type=str, choices=["bratto", "unionmonthly"], help="Source site to reparse (default: both)")
    parser_floors.add_argument("--storage-root", type=str, help="Directory containing raw HTML files (matched by basename; default: use storage_path as-is)")
    parser_floors.add_argument("--limit", type=int, help="Process only first N properties (testing)")
    parser_floors.add_argument("--dry-run", action="store_true", help="Report the diff without writing")

    # reparse-orientation
    parser_orient = subparsers.add_parser(
        "reparse-orientation",
        help="Reparse orientation from saved raw HTML (docs/orientation-model-plan.md)",
    )
    parser_orient.add_argument("--source", type=str, choices=["bratto", "unionmonthly"], default="unionmonthly", help="Source site to reparse (default: unionmonthly)")
    parser_orient.add_argument("--storage-root", type=str, help="Directory containing raw HTML files (matched by basename; default: use storage_path as-is)")
    parser_orient.add_argument("--limit", type=int, help="Process only first N properties (testing)")
    parser_orient.add_argument("--dry-run", action="store_true", help="Report the diff without writing")

    # reparse-point
    parser_point = subparsers.add_parser(
        "reparse-point",
        help="Reparse staff comment (point_text) from saved raw HTML (unionmonthly)",
    )
    parser_point.add_argument("--source", type=str, default="unionmonthly", help="Source site id to reparse (unionmonthly only)")
    parser_point.add_argument("--storage-root", type=str, help="Directory containing raw HTML files (matched by basename; default: use storage_path as-is)")
    parser_point.add_argument("--limit", type=int, help="Process only first N properties (testing)")
    parser_point.add_argument("--dry-run", action="store_true", help="Report the diff without writing")

    # building-identity / building-merge / building-split (建物集約 B1・§5)
    parser_bidentity = subparsers.add_parser(
        "building-identity",
        help="Building identity batch: dry-run report or apply (docs/building-aggregation-design.md §5)",
    )
    parser_bidentity.add_argument("--apply", action="store_true", help="Apply assignments and recompute representatives (default: dry-run, no writes)")
    parser_bidentity.add_argument("--json", action="store_true", help="Also print the full report as JSON")

    parser_bmerge = subparsers.add_parser(
        "building-merge",
        help="Merge building B into building A (manual override, design §5)",
    )
    parser_bmerge.add_argument("building_a", type=int, help="Surviving building id")
    parser_bmerge.add_argument("building_b", type=int, help="Building id to merge into A")

    parser_bsplit = subparsers.add_parser(
        "building-split",
        help="Split rooms into a new building (same-address multi-block cases, design §10)",
    )
    parser_bsplit.add_argument("building_id", type=int, help="Source building id")
    parser_bsplit.add_argument(
        "--property-ids", type=str, required=True,
        help="Comma-separated property ids to move to the new building",
    )

    # backfill-embeddings (PG移行 Phase 7a・意味検索 / Batch API 経路)
    parser_bemb = subparsers.add_parser(
        "backfill-embeddings",
        help="Batch-generate property embeddings via Gemini Batch API (default) or sync fallback",
    )
    parser_bemb.add_argument("--limit", type=int, help="Process only first N visible properties (testing)")
    parser_bemb.add_argument("--dry-run", action="store_true", help="Report pending count without calling the embedding API")
    parser_bemb.add_argument(
        "--mode",
        choices=["batch", "sync"],
        default="batch",
        help="batch = Gemini Batch API (default, 50%% cost, no rate-limit burst); sync = serial embedContent fallback",
    )
    parser_bemb.add_argument(
        "--wait-secs",
        type=int,
        default=300,
        help="Bounded wait for submitted batch jobs to finish before exiting (batch mode)",
    )
    parser_bemb.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Max requests per batch job (batch mode, plan D4)",
    )
    parser_bemb.add_argument(
        "--submit-only",
        action="store_true",
        help="Submit batch jobs and exit without waiting (results applied on a later run)",
    )

    # media-backfill (rustfs クラスタ代表ストア・docs/media-storage-rustfs-plan.md)
    parser_mbf = subparsers.add_parser(
        "media-backfill",
        help="Fetch property images into the rustfs media store (cluster-representative dedup)",
    )
    parser_mbf.add_argument("--limit", type=int, help="Process only first N pending rows (testing)")
    parser_mbf.add_argument("--dry-run", action="store_true", help="Report pending count without fetching")
    parser_mbf.add_argument("--source", type=str, help="Filter by source_site (unionmonthly / bratto)")
    parser_mbf.add_argument("--retry-failed", action="store_true", help="Also retry rows marked failed")

    args = parser.parse_args()

    if args.command == "db-init":
        cmd_db_init(args)
    elif args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "export-map":
        cmd_export_map(args)
    elif args.command == "geocode":
        cmd_geocode(args)
    elif args.command == "report-unmapped-features":
        cmd_report_unmapped_features(args)
    elif args.command == "reparse-features":
        cmd_reparse_features(args)
    elif args.command == "reparse-floors":
        cmd_reparse_floors(args)
    elif args.command == "reparse-orientation":
        cmd_reparse_orientation(args)
    elif args.command == "reparse-point":
        cmd_reparse_point(args)
    elif args.command == "building-identity":
        cmd_building_identity(args)
    elif args.command == "building-merge":
        cmd_building_merge(args)
    elif args.command == "building-split":
        cmd_building_split(args)
    elif args.command == "backfill-embeddings":
        rc = cmd_backfill_embeddings(args)
        if rc:
            sys.exit(rc)
    elif args.command == "media-backfill":
        rc = cmd_media_backfill(args)
        if rc:
            sys.exit(rc)
    elif args.command == "run-mcp":
        from mcp_server import run_mcp_server

        run_mcp_server()

if __name__ == "__main__":
    main()
