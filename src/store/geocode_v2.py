"""Geocode batch for the v2 data layer.

docs/geocode-v2-batch-spec.md §3 準拠:
- モード別 WHERE (§3.3): default / force / retry_only（filter_expr は廃止）
- 状態遷移 (§3.1): 成功 / ソフト失敗(unchanged or failed:) / システムエラー(無書き込み skip) /
  予期せぬ例外(無書き込み skip + traceback ログ)
- 不変条件 (§3.2 I1-I4): 失敗印は座標なし行のみ・障害は痕跡を残さない・既存座標は破壊しない・
  failed:<X> の X は実プロバイダ名のみ（'default' 生成禁止）
- 統計 (§3.4): total_found / processed / success / failed / skipped / unchanged / remaining
- サーキットブレーカ (§3.5): 連続 3 回の GeocodingSystemError で打ち切り (stats["aborted"]=True)
- 行単位コミット (§3.6)、provider バリデーション (§3.7)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from store.geocoder import GeocodingSystemError, geocode_address
from store.repository import Repository

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


def geocode_missing_v2(
    limit: Optional[int] = 100,
    *,
    provider: Optional[str] = None,
    force: bool = False,
    retry_only: bool = False,
) -> dict[str, Any]:
    """Geocode v2 properties selected by mode; returns §3.4 stats.

    - provider: None (google 先行 auto) / 'nominatim' / 'google'。範囲外は ValueError (§3.7)。
    - force: address を持つ全件が対象。retry_only: geocode_source が何らかの値の行が対象。
    - limit は選択行への予算方式（§3.4。total_found は予算前の選択行数）。
    """
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(
            f"invalid provider: {provider!r} (expected one of None, 'nominatim', 'google')"
        )
    mode = _resolve_mode(force=force, retry_only=retry_only)

    repo = Repository()
    conn = repo.connect()
    try:
        rows = list(
            conn.execute(
                f"""
                SELECT id, address, title, lat, lng FROM properties
                WHERE {_MODE_WHERE[mode]}
                ORDER BY id
                """
            )
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
                # §3.1-3: 一切書き込まない（I2）
                stats["skipped"] += 1
                stats["processed"] += 1
                consecutive_system_errors += 1
                logger.warning(
                    "geocode_v2: system error on property id=%s: %s", row["id"], e
                )
                if consecutive_system_errors >= _CONSECUTIVE_SYSTEM_ERROR_LIMIT:
                    # §3.5 サーキットブレーカ
                    stats["aborted"] = True
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
                    "geocode_v2: unexpected error on property id=%s", row["id"]
                )
                continue

            consecutive_system_errors = 0

            if lat is not None and lng is not None:
                # §3.1-1: 成功 → 座標 + source + confidence を更新
                conn.execute(
                    """
                    UPDATE properties
                    SET lat = ?, lng = ?, geocode_source = ?, geocode_confidence = ?
                    WHERE id = ?
                    """,
                    (lat, lng, source, confidence, row["id"]),
                )
                conn.commit()
                stats["success"] += 1
            elif row["lat"] is not None or row["lng"] is not None:
                # §3.1-2a: 既存座標がある → 何も書き換えない（I1/I3）
                stats["unchanged"] += 1
            else:
                # §3.1-2b: ソフト失敗 → 実プロバイダ名で失敗印（I4、'default' 生成禁止）
                failed_source = source or provider or "nominatim"
                conn.execute(
                    "UPDATE properties SET geocode_source = ? WHERE id = ?",
                    (f"failed:{failed_source}", row["id"]),
                )
                conn.commit()
                stats["failed"] += 1
            stats["processed"] += 1

        # §3.4
        stats["remaining"] = max(0, stats["total_found"] - stats["processed"])
        return stats
    finally:
        conn.close()
