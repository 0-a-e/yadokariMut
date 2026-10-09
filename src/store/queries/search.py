"""物件検索系クエリ: 検索 / 件数 / PK 一括取得."""

from __future__ import annotations

from typing import Any, Sequence

from domain.feature_resolution import (
    FeatureRequirement,
    resolve_requirements,
    satisfiable_codes_from_categories,
)
from store.pg import open_connection
from store.queries._common import (
    _CHILD_IN_CHUNK,
    _FEATURES_CHILD_SQL,
    _fetch_child_rows_by_property,
    _property_list_sql,
    _property_row_to_result,
    _repo,
    MIN_WALK_SUBQUERY,
    fetch_standard_child_maps,
)


def _search_where(params: dict[str, Any]) -> tuple[list[str], list[Any]]:
    """検索系クエリ(iter_search_properties / buildings._matching_room_ids)共通の WHERE 句を構築する.

    可視性 (is_active / shortlist 状態) と絞り込み条件 (県 / ソース / 面積 /
    saved_only / exclude_hidden) を SQL 句へ変換する。required_features /
    max_walk は _required_feature_clauses / min_walk_minutes derived table で、
    max_monthly のみ Python 側 post filter で担当する (決定 10)。
    """
    prefecture_name = params.get("prefecture_name")
    source_sites = params.get("source_sites")
    if isinstance(source_sites, str):
        source_sites = [s.strip() for s in source_sites.split(",") if s.strip()]
    min_area = params.get("min_area_m2")
    saved_only = params.get("saved_only", False)
    exclude_hidden = params.get("exclude_hidden", True)

    # Shortlisted properties stay visible even when the source site drops
    # them (is_active = false) — the FE/MCP/AI mark them as inactive instead.
    clauses = ["(p.is_active OR s.status IN ('saved', 'hide', 'reject'))"]
    qparams: list[Any] = []
    if prefecture_name:
        clauses.append("p.prefecture_name = %s")
        qparams.append(prefecture_name)
    if source_sites:
        ph = ",".join("%s" for _ in source_sites)
        clauses.append(f"p.source_site IN ({ph})")
        qparams.extend(source_sites)
    if min_area is not None:
        clauses.append("p.area_m2 >= %s")
        qparams.append(min_area)
    if saved_only:
        clauses.append("s.status = 'saved'")
    elif exclude_hidden:
        clauses.append("(s.status IS NULL OR s.status NOT IN ('hide', 'reject'))")
    return clauses, qparams


def _resolve_required_features(params: dict[str, Any]) -> list[FeatureRequirement]:
    """required_features の正規化 (CSV 分割) と解決 (設計 §3.2)。

    CSV 正規化の正本は queries 層 (H2)。code 要件 (辞書/親/横断/寛容受入) と
    生名 fallback への振り分けは domain.feature_resolution が担う。
    """
    required_features = params.get("required_features")
    if isinstance(required_features, str):
        required_features = [x.strip() for x in required_features.split(",") if x.strip()]
    return resolve_requirements(required_features)


def _required_feature_clauses(
    requirements: list[FeatureRequirement], qparams: list[Any]
) -> list[str]:
    """要件ごとの EXISTS 前段述語を構築する (決定 10・単一 SQL 前段経路)。

    code 要件は `pf.category IN (解決 code 集合)`、生名 fallback 要件は
    `pf.feature_name = %s` (実値完全一致) で表現し、併存する場合は同一 EXISTS 内の
    OR で結合する。解決結果の正本は domain.feature_resolution (呼び出し側で
    resolve 済みのため、ここで解決ロジックを SQL 側に埋め直さない)。
    """
    clauses: list[str] = []
    for req in requirements:
        predicates: list[str] = []
        code_list = sorted(req.codes)
        if code_list:
            ph = ",".join("%s" for _ in code_list)
            predicates.append(f"pf.category IN ({ph})")
            qparams.extend(code_list)
        if req.is_fallback:
            predicates.append("pf.feature_name = %s")
            qparams.append(req.raw)
        if not predicates:
            continue  # 空要件は全物件通過 (解決器の契約上発生しない)
        clauses.append(
            "EXISTS (SELECT 1 FROM property_features pf "
            f"WHERE pf.property_id = p.id AND ({' OR '.join(predicates)}))"
        )
    return clauses


# min_walk_minutes は _property_list_sql SELECT 内の相関サブクエリ列のため
# 同一レベルの WHERE では参照できない (SQLite の別名解決は GROUP BY / ORDER BY /
# HAVING のみ)。max_walk の SQL 化 (決定 10) では derived table で 1 段 wrap し、
# 外側 WHERE で絞る (ORDER BY / LIMIT も外側に置く)。
_MIN_WALK_FILTER = "(min_walk_minutes IS NULL OR min_walk_minutes <= %s)"
# id タイブレークで決定性を担保(Phase 6c parity で BOOLEAN 化に伴う実行計画差で
# 同値グループ内の順序が変わることを確認 — _ROOM_ORDER_BY と対称の修正)
_SEARCH_ORDER_BY = (
    "ORDER BY p.is_active DESC, p.catalog_rent_per_day_yen IS NULL, "
    "p.catalog_rent_per_day_yen ASC, p.id ASC"
)
_SEARCH_ORDER_BY_WRAPPED = (
    "ORDER BY is_active DESC, catalog_rent_per_day_yen IS NULL, "
    "catalog_rent_per_day_yen ASC, id ASC"
)


def _building_context_map(conn, rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """部屋行 chunk から建物 id → {name, shortlist_status} の文脈マップ(KML 用).

    building_id 未割当 (None) の部屋は対象外。建物ショートリストは saved の
    み取得する(スタイル判定 stBuildingSaved のため)。
    """
    bids = sorted({int(r["building_id"]) for r in rows if r.get("building_id")})
    if not bids:
        return {}
    ph = ",".join("%s" for _ in bids)
    out: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        f"SELECT b.id, b.canonical_name, bs.status FROM buildings b"
        f" LEFT JOIN building_shortlists bs ON bs.building_id = b.id"
        f" WHERE b.id IN ({ph})",
        bids,
    ):
        out[int(row["id"])] = {
            "name": row["canonical_name"],
            "shortlist_status": row["status"],
        }
    return out


def iter_search_properties(
    params: dict[str, Any] | None = None,
    *,
    state: dict[str, Any] | None = None,
):
    """search_properties のジェネレータ版。検索結果を 1 物件ずつ yield する.

    WHERE 句 (required_features EXISTS 前段 + max_walk derived table 絞り込み) /
    over-fetch (fetch_limit) / max_monthly 後フィルタ / limit 到達で停止 /
    ORDER BY / 戻り値の順序と内容は search_properties と完全に同一。
    子テーブルの取得は物件ごとの個別クエリ(N+1)を避けつつメモリと TTFB を
    押さえるため、候補を _CHILD_IN_CHUNK 件ずつのチャンクに分けて IN 一括取得する。
    接続は open_connection() で開き、途中で破棄されても閉じられる。

    state を渡すと走査の終わり方を書き戻す(決定 6 の candidates_exhausted)。
    True = 候補を最後まで消費した(over-fetch 残存時の静かな過少返却はこれで
    切り分ける)、False = limit 到達で打ち切り。
    """
    params = params or {}
    max_walk = params.get("max_walk_minutes")
    # required_features の解決正本はここ(queries 層)。
    # _required_feature_clauses が EXISTS 前段述語へ載せる(決定 10)
    requirements = _resolve_required_features(params)
    limit = int(params.get("limit") or 50)
    max_monthly = params.get("max_monthly_total_yen")

    clauses, where_params = _search_where(params)
    clauses.extend(_required_feature_clauses(requirements, where_params))

    # over-fetch は max_monthly_total_yen のみに残存(決定 10 — 実効値が
    # Python 側集計のため SQL 表現不能)。required_features / max_walk は
    # 前段 SQL に入ったため limit そのままで取りこぼしが出ない
    fetch_limit = max(limit * 20, 500) if max_monthly else limit

    if max_walk is not None:
        inner_sql = _property_list_sql(f"WHERE {' AND '.join(clauses)}")
        sql = f"""
            SELECT * FROM ({inner_sql})
            WHERE {_MIN_WALK_FILTER}
            {_SEARCH_ORDER_BY_WRAPPED}
            LIMIT %s
        """
        qparams = [*where_params, max_walk, fetch_limit]
    else:
        sql = _property_list_sql(
            f"WHERE {' AND '.join(clauses)} {_SEARCH_ORDER_BY} LIMIT %s"
        )
        qparams = [*where_params, fetch_limit]

    with open_connection() as conn:
        rows = [dict(r) for r in conn.execute(sql, qparams)]

        emitted = 0
        # 候補全件分の子テーブルを先に取得するとメモリが膨らむため、
        # チャンクごとに IN 一括取得 → チャンク内の行を順に処理して yield する
        for start in range(0, len(rows), _CHILD_IN_CHUNK):
            chunk = rows[start : start + _CHILD_IN_CHUNK]
            pids = [row["id"] for row in chunk]

            maps = fetch_standard_child_maps(conn, pids)
            # 配信契約(設計 §3.3)により全検索で features を取得して
            # feature_categories(充足可能 code 集合)を各物件に載せる。
            # required 判定は SQL 前段へ移行済みのため取得は配信専用
            feature_map = _fetch_child_rows_by_property(
                conn,
                _FEATURES_CHILD_SQL,
                pids,
            )
            # 建物文脈(§6.3・KML 用)。チャンク内の building_id から建物名と
            # 建物ショートリスト状態(saved)を一括取得する
            building_ctx = _building_context_map(conn, chunk)

            for row in chunk:
                pid = row["id"]
                result = _property_row_to_result(
                    row,
                    maps.access.get(pid, []),
                    maps.image.get(pid, []),
                    maps.plan.get(pid, []),
                    maps.campaign.get(pid, []),
                )
                result["feature_categories"] = satisfiable_codes_from_categories(
                    [r["category"] for r in feature_map.get(pid, [])]
                )
                binfo = building_ctx.get(row.get("building_id"))
                if binfo is not None:
                    result["building_id"] = row.get("building_id")
                    result["building_name"] = binfo.get("name")
                    result["building_shortlist_status"] = binfo.get("shortlist_status")
                if (
                    max_monthly is not None
                    and result.get("min_plan_total") is not None
                    and result["min_plan_total"] > max_monthly
                ):
                    continue
                yield result
                emitted += 1
                if emitted >= limit:
                    if state is not None:
                        state["candidates_exhausted"] = False
                    return
        if state is not None:
            state["candidates_exhausted"] = True


def search_properties(
    params: dict[str, Any] | None = None,
    *,
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """検索条件に一致する物件リストを返す (iter_search_properties の全件取得).

    limit の既定差は呼び出し層の契約 (意図的な違い):
    - MCP (mcp_server.search_properties): 既定 50 (エージェント UX 向けの絞り込み一覧)
    - API 全件取得系 (/api/geojson, export_geojson / export_kml の既定): 10000
    本関数自身の既定 (params に limit 無し) は 50。上限値 (10000) は双方共通。
    """
    return list(iter_search_properties(params, state=state))




def get_properties_by_ids(ids: Sequence[int]) -> list[dict[str, Any]]:
    """PK id の完全一致で物件を取得する (FEエクスポート用).

    search_properties と異なり is_active や shortlist 状態による可視性の
    絞り込みを行わず、座標の有無に関係なく指定 id をすべて返す。
    戻り値の順序は入力 ids の順を維持する (不明 id はスキップ)。

    建物単位集約モデル (設計 §6.3): KML ExtendedData 用に building_id /
    building_name (buildings.canonical_name) を搭載する。主問合せは
    _property_list_sql をそのまま使い、建物列のみ derived table wrap で
    LEFT JOIN して付与する (未割当は NULL)。
    """
    seen: set[int] = set()
    unique_ids = [i for i in (int(x) for x in ids) if not (i in seen or seen.add(i))]
    if not unique_ids:
        return []

    with open_connection() as conn:
        rows_by_id: dict[int, dict[str, Any]] = {}
        for start in range(0, len(unique_ids), _CHILD_IN_CHUNK):
            chunk = unique_ids[start : start + _CHILD_IN_CHUNK]
            ph = ",".join("%s" for _ in chunk)
            sql = (
                "SELECT q.*, b.canonical_name AS building_name,"
                " bs.status AS building_shortlist_status FROM ("
                + _property_list_sql(f"WHERE p.id IN ({ph})")
                + ") q LEFT JOIN buildings b ON b.id = q.building_id"
                " LEFT JOIN building_shortlists bs ON bs.building_id = q.building_id"
            )
            for row in conn.execute(sql, chunk):
                rows_by_id[row["id"]] = dict(row)

        pids = list(rows_by_id.keys())
        maps = fetch_standard_child_maps(conn, pids)
        # KML/FE エクスポート経路でも配信契約(設計 §3.3)どおり
        # feature_categories を搭載する(iter_search_properties と同一の出力構成)
        feature_map = _fetch_child_rows_by_property(conn, _FEATURES_CHILD_SQL, pids)

        results: list[dict[str, Any]] = []
        for pid in unique_ids:
            row = rows_by_id.get(pid)
            if row is None:
                continue
            result = _property_row_to_result(
                row,
                maps.access.get(pid, []),
                maps.image.get(pid, []),
                maps.plan.get(pid, []),
                maps.campaign.get(pid, []),
            )
            result["feature_categories"] = satisfiable_codes_from_categories(
                [r["category"] for r in feature_map.get(pid, [])]
            )
            # 建物文脈 (KML ExtendedData 用・設計 §6.3)。未割当は None のまま。
            # building_shortlist_status は KML の stBuildingSaved 判定用
            result["building_id"] = row.get("building_id")
            result["building_name"] = row.get("building_name")
            result["building_shortlist_status"] = row.get("building_shortlist_status")
            results.append(result)
        return results
