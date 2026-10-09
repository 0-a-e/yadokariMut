"""Geocode batch for the v2 data layer.

B2-ε で建物単位化 (docs/building-aggregation-design.md §9 B2): 建物テーブルを
第一対象とし、成功時は所属部屋(座標 NULL の行のみ)へ代表座標を backfill する。
未割当(building_id NULL)の部屋のみ従来の部屋単位パスで処理する。建物の
代表座標は名寄せバッチの多数決で部屋行から再導出されるため、backfill は
「部屋行も埋める」ことで再計算と整合する(設計: 部屋行が取得事実の正本)。

docs/geocode-v2-batch-spec.md §3 準拠:
- モード別 WHERE (§3.3): default / force / retry_only（filter_expr は廃止）
- 状態遷移 (§3.1): 成功 / ソフト失敗(unchanged or failed:) / システムエラー(無書き込み skip) /
  予期せぬ例外(無書き込み skip + traceback ログ)
- 不変条件 (§3.2 I1-I4): 失敗印は座標なし行のみ・障害は痕跡を残さない・既存座標は破壊しない・
  failed:<X> の X は実プロバイダ名のみ（'default' 生成禁止）
- 統計 (§3.4): total_found / processed / success / failed / skipped / unchanged / remaining
- サーキットブレーカ (§3.5): 連続 3 回の GeocodingSystemError で打ち切り (stats["aborted"]=True)
- 行単位コミット (§3.6)、provider バリデーション (§3.7)
- 警告文言の正本 (§3.8): geocode_result_warnings / format_geocode_warnings。
  cli / mcp / web tasks はこの formatter 経由でのみ文言を生成する
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Optional

from store.geocoder import GeocodingSystemError, geocode_address
from store.pg import open_connection

logger = logging.getLogger(__name__)

ALLOWED_PROVIDERS = (None, "nominatim", "google")

# §3.5: 連続この回数だけ GeocodingSystemError が続いたらバッチを打ち切る
_CONSECUTIVE_SYSTEM_ERROR_LIMIT = 3

# モード別 WHERE (§3.3)
_MODE_WHERE = {
    "default": (
        "address IS NOT NULL "
        "AND (lat IS NULL OR lng IS NULL) "
        "AND (geocode_source IS NULL OR geocode_source NOT LIKE 'failed%')"
    ),
    "force": "address IS NOT NULL",
    "retry_only": "geocode_source IS NOT NULL",
}

# B2-ε: パス別の追加条件。建物パスは buildings 表そのもの、部屋パスは
# 未割当(building_id IS NULL)の行のみ(建物に属する部屋は建物 geocode の
# backfill またはスクレイプ時のページ座標で賄われる)
_ROOMS_EXTRA_WHERE = " AND building_id IS NULL"


def _resolve_mode(*, force: bool, retry_only: bool) -> str:
    if force and retry_only:
        raise ValueError("force and retry_only are mutually exclusive")
    if force:
        return "force"
    if retry_only:
        return "retry_only"
    return "default"


def validate_geocode_args(
    limit: Optional[int] = None,
    *,
    force: bool = False,
    provider: Optional[str] = None,
    retry_only: bool = False,
    filter_expr: Optional[str] = None,
) -> None:
    """geocode バッチ引数の API/MCP 共通バリデーション (§3.7)。違反は ValueError.

    web_server.trigger_geocode (HTTP 422 に変換) と
    mcp_server.geocode_properties (status:error 応答に変換) の双方から使う。
    3 ルール: filter_expr 拒否 / provider 白色リスト / force≠retry_only 排他。

    - filter_expr は v2 が解釈しない廃止パラメータ (spec §3.7)。渡されたら明示拒否
    - provider は None (google 先行 auto) / nominatim / google のみ
    - limit はバッチ予算として geocode_missing_v2 へそのまま渡る値で、
      ここでは検証しない (web_server 既定 20 / MCP 既定 20)
    """
    if filter_expr:
        raise ValueError(
            "filter_expr is no longer supported. Use force / retry_only instead."
        )
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(
            f"Invalid provider: {provider}. Must be one of: nominatim, google."
        )
    if force and retry_only:
        raise ValueError("force and retry_only are mutually exclusive.")


def _geocode_pass(
    conn,
    *,
    table: str,
    select_sql: str,
    update_sql: str,
    failed_update_sql: str,
    backfill_sql: str | None,
    limit: Optional[int],
    provider: Optional[str],
    mode: str,
) -> dict[str, Any]:
    """1 パス分のジオコーディング(state machine は §3.1 と同一)。

    select_sql は {mode_where} を含む SELECT(行は id/address/lat/lng を返す)。
    backfill_sql は成功時に発行する伝播 UPDATE(建物パスのみ・None でスキップ)。
    """
    rows = list(
        conn.execute(select_sql.format(mode_where=_MODE_WHERE[mode]))
    )
    selected = rows if limit is None else rows[: int(limit)]

    stats: dict[str, Any] = {
        "total_found": len(rows),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "unchanged": 0,
        "remaining": len(rows),
    }

    consecutive_system_errors = 0
    for i, row in enumerate(selected):
        if i > 0:
            # Inter-request delay to honor API usage policies
            time.sleep(1.2 if provider != "google" else 0.1)

        # §3.1: 1 行あたりの状態遷移
        try:
            lat, lng, source, confidence = geocode_address(
                row["address"], provider=provider
            )
        except GeocodingSystemError as e:
            # §3.1-3: 一切書き込まない(I2)
            stats["skipped"] += 1
            stats["processed"] += 1
            consecutive_system_errors += 1
            logger.warning(
                "geocode_v2: system error on %s id=%s: %s", table, row["id"], e
            )
            if consecutive_system_errors >= _CONSECUTIVE_SYSTEM_ERROR_LIMIT:
                # §3.5 サーキットブレーカ
                stats["aborted"] = True
                stats["consecutive_system_errors"] = consecutive_system_errors
                logger.warning(
                    "geocode_v2: aborted after %d consecutive system errors",
                    consecutive_system_errors,
                )
                break
            continue
        except Exception:
            # §3.1-4: 予期せぬ例外も無書き込み skip + traceback ログ
            stats["skipped"] += 1
            stats["processed"] += 1
            consecutive_system_errors = 0
            logger.exception(
                "geocode_v2: unexpected error on %s id=%s", table, row["id"]
            )
            continue

        consecutive_system_errors = 0

        if lat is not None and lng is not None:
            # §3.1-1: 成功 → 座標 + source + confidence を更新
            conn.execute(
                update_sql,
                (lat, lng, source, confidence, row["id"]),
            )
            if backfill_sql is not None:
                # 建物パス: 所属部屋の座標 NULL 行へ代表座標を伝播
                # (部屋行が取得事実の正本のため、名寄せ再計算の多数決と整合する)
                conn.execute(backfill_sql, (lat, lng, row["id"]))
            conn.commit()
            stats["success"] += 1
        elif row["lat"] is not None or row["lng"] is not None:
            # §3.1-2a: 既存座標がある → 何も書き換えない(I1/I3)
            stats["unchanged"] += 1
        else:
            # §3.1-2b: ソフト失敗 → 実プロバイダ名で失敗印(I4、'default' 生成禁止)
            failed_source = source or provider or "nominatim"
            conn.execute(
                failed_update_sql,
                (f"failed:{failed_source}", row["id"]),
            )
            conn.commit()
            stats["failed"] += 1
        stats["processed"] += 1

    # §3.4
    stats["remaining"] = max(0, stats["total_found"] - stats["processed"])
    return stats


def _merge_stats(base: dict[str, Any], extra: dict[str, Any]) -> None:
    """2 パスの統計を合算(スカラー数値のみ。aborted は truthy を優先反映)。"""
    for key in ("total_found", "processed", "success", "failed", "skipped",
                "unchanged", "remaining"):
        base[key] = int(base.get(key) or 0) + int(extra.get(key) or 0)
    if extra.get("aborted"):
        base["aborted"] = True
        base["consecutive_system_errors"] = extra.get("consecutive_system_errors")


def geocode_missing_v2(
    limit: Optional[int] = 100,
    *,
    provider: Optional[str] = None,
    force: bool = False,
    retry_only: bool = False,
) -> dict[str, Any]:
    """建物単位ジオコーディングバッチ(B2-ε)。§3.4 stats を返す。

    パス構成:
    1. buildings パス: 座標欠落の建物を住所でジオコーディングし、成功時に
       所属部屋(座標 NULL 行のみ)へ代表座標を backfill
    2. rooms パス: 未割当(building_id IS NULL)の部屋のみ従来どおり処理

    - provider: None (google 先行 auto) / 'nominatim' / 'google'。範囲外は ValueError (§3.7)。
    - force: address を持つ全件が対象。retry_only: geocode_source が何らかの値の行が対象。
    - limit はバッチ予算(§3.4)。建物パスが消費した残りを部屋パスへ回す。
      stats のトップレベルは両パスの合計、内訳は stats["targets"] に保持する。
    """
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(
            f"invalid provider: {provider!r} (expected one of None, 'nominatim', 'google')"
        )
    mode = _resolve_mode(force=force, retry_only=retry_only)

    building_select = (
        "SELECT id, address, lat, lng FROM buildings "
        "WHERE {mode_where} ORDER BY id"
    )
    building_update = (
        "UPDATE buildings SET lat = %s, lng = %s, geocode_source = %s, "
        "geocode_confidence = %s WHERE id = %s"
    )
    building_failed_update = (
        "UPDATE buildings SET geocode_source = %s WHERE id = %s"
    )
    building_backfill = (
        "UPDATE properties SET lat = %s, lng = %s "
        "WHERE building_id = %s AND lat IS NULL AND lng IS NULL"
    )
    room_select = (
        "SELECT id, address, lat, lng FROM properties "
        "WHERE {mode_where}" + _ROOMS_EXTRA_WHERE + " ORDER BY id"
    )
    room_update = (
        "UPDATE properties SET lat = %s, lng = %s, geocode_source = %s, "
        "geocode_confidence = %s WHERE id = %s"
    )
    room_failed_update = (
        "UPDATE properties SET geocode_source = %s WHERE id = %s"
    )

    with open_connection() as conn:
        building_stats = _geocode_pass(
            conn,
            table="buildings",
            select_sql=building_select,
            update_sql=building_update,
            failed_update_sql=building_failed_update,
            backfill_sql=building_backfill,
            limit=limit,
            provider=provider,
            mode=mode,
        )
        remaining_budget = (
            None
            if limit is None
            else max(0, int(limit) - int(building_stats["processed"]))
        )
        room_stats = _geocode_pass(
            conn,
            table="properties(unassigned)",
            select_sql=room_select,
            update_sql=room_update,
            failed_update_sql=room_failed_update,
            backfill_sql=None,
            limit=remaining_budget,
            provider=provider,
            mode=mode,
        )

    merged = dict(building_stats)
    _merge_stats(merged, room_stats)
    merged["targets"] = {"buildings": building_stats, "rooms": room_stats}
    return merged


# ---------------------------------------------------------------------------
# 警告文言の正本 (§3.5 / §3.8)。cli / mcp_server / web tasks はここ経由のみ。
# ---------------------------------------------------------------------------

# §3.8 契約文言: 言語によらず日本語固定(SPEC 一文字変更禁止)
_SKIPPED_WARNING_TEMPLATE = (
    "warn: {count} 件はプロバイダ障害等のため記録なしスキップ。"
    "時間を置いて再実行してください"
)

# aborted は層ごとの言語慣習に合わせて ja/en を用意(cli/tasks=ja, mcp=en)。
# 連続数は stats["consecutive_system_errors"](skipped は累計で意味が異なる)
_ABORTED_WARNING_TEMPLATES = {
    "ja": "warn: 連続 {consecutive} 回のプロバイダ障害のため"
    "サーキットブレーカにより打ち切りしました",
    "en": "warn: geocode aborted by circuit breaker "
    "after {consecutive} consecutive provider system errors",
}


def geocode_result_warnings(stats: Mapping[str, Any]) -> list[dict[str, Any]]:
    """§3.5/§3.8 の警告を構造化して返す。

    [{"code": "skipped", "count": N}, {"code": "aborted", "consecutive": N}, ...]

    - skipped: システムエラー + 予期せぬ例外の累計(無書き込み skip の総数)
    - aborted/consecutive: サーキットブレーカ打切り時点の「連続」システムエラー数。
      キーが無い stats(旧実行結果など)は打切り条件と一致する既定値を当てる
    """
    warnings: list[dict[str, Any]] = []
    skipped = int(stats.get("skipped") or 0)
    if skipped:
        warnings.append({"code": "skipped", "count": skipped})
    if stats.get("aborted"):
        consecutive = int(
            stats.get("consecutive_system_errors") or _CONSECUTIVE_SYSTEM_ERROR_LIMIT
        )
        warnings.append({"code": "aborted", "consecutive": consecutive})
    return warnings


def format_geocode_warnings(
    warnings: list[dict[str, Any]], *, lang: str = "ja"
) -> list[str]:
    """警告行リストへ整形(skipped 行は常に日本語の契約文言)。"""
    lines: list[str] = []
    for warning in warnings:
        code = warning.get("code")
        if code == "skipped":
            lines.append(_SKIPPED_WARNING_TEMPLATE.format(count=warning.get("count", 0)))
        elif code == "aborted":
            template = _ABORTED_WARNING_TEMPLATES.get(lang, _ABORTED_WARNING_TEMPLATES["ja"])
            lines.append(
                template.format(
                    consecutive=warning.get("consecutive", _CONSECUTIVE_SYSTEM_ERROR_LIMIT)
                )
            )
    return lines
