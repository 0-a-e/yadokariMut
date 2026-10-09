"""Per-source rotation overrides persistence (v2 DB app_settings, key='rotation_settings').

保存対象は県ローテーション計画パラメタの「上書き値」のみ:

    {"sources": {"bratto": {"daily_limit": 800, "default_est": 60}}}

- 1キー1行JSONで app_settings に保存する (読み書きの共通実装は
  store.app_settings.JsonSettingsStore。null=削除の部分マージ契約も同参照)
- 実行時は run_rotation_job がジョブ開始時に resolve_effective_limits() で
  実効値を解決するため、DB 変更は再起動不要で次回実行から反映される
- daily_limit は 1 日あたりの取得予算(件)、default_est は known_total 未計測県の
  予算見積り件数。0 は予算枯渇(daily_budget_exhausted)扱いになるため無効
  (旧 ROTATION_DAILY_LIMIT_{SID} / ROTATION_DEFAULT_EST 環境変数は廃止)
"""

from __future__ import annotations

from typing import Any, Optional

from store.app_settings import (
    JsonSettingsStore,
    known_source_ids,
    validate_int_or_null,
    validate_source_id,
)

_SETTINGS_KEY = "rotation_settings"
_SOURCE_KEYS = {"daily_limit", "default_est"}

# 0 はプランナで予算枯渇扱いになるため下限 1
_LIMIT_MIN, _LIMIT_MAX = 1, 10000

# コード既定(旧 ROTATION_DAILY_LIMIT_{SID} 既定 500 / ROTATION_DEFAULT_EST 既定 60)
DEFAULT_DAILY_LIMIT = 500
DEFAULT_EST = 60


def _validate_source_entry_id(source_id: Any) -> None:
    validate_source_id(source_id, known_source_ids())


_store = JsonSettingsStore(
    _SETTINGS_KEY,
    ("sources",),
    keyed=("sources",),
    allowed_keys={"sources": _SOURCE_KEYS},
    validators={
        "sources": {
            key: (lambda v, where: validate_int_or_null(v, _LIMIT_MIN, _LIMIT_MAX, where))
            for key in sorted(_SOURCE_KEYS)
        }
    },
    entry_id_validator=_validate_source_entry_id,
)


def get_rotation_settings() -> dict:
    """Load saved per-source overrides. Returns {"sources": {}} when unset."""
    return _store.load()


def save_rotation_settings(update: Any) -> dict:
    """Partial-merge save. Returns the full settings after save.

    - update.sources.<id>.<key> = 値   → そのキーのみ上書き
    - update.sources.<id>.<key> = null → その保存済みキーを削除(既定へ戻す)
    - update.sources.<id> = null       → そのソースの保存全体を削除

    不正な値は ValueError。呼び出し側(web_server)が HTTPException(400) にする。
    """
    return _store.save(update)


def resolve_effective_limits(
    source_id: str
) -> dict:
    """実効値 {daily_limit, default_est} を返す(保存値 > コード既定).

    スケジューラ・手動実行ともジョブ開始時に呼ぶ。SOURCE_CATALOG 外の
    source id も既定値にフォールバックして解決する。
    """
    saved = get_rotation_settings()["sources"].get(source_id) or {}
    return {
        "daily_limit": int(saved.get("daily_limit", DEFAULT_DAILY_LIMIT)),
        "default_est": int(saved.get("default_est", DEFAULT_EST)),
    }


def effective_rotation_settings() -> dict:
    """Admin UI 用: ソース別の保存済み上書き + 実効値 + 既定値を返す。"""
    from store.source_catalog import SOURCE_CATALOG

    ids = [str(entry["id"]) for entry in SOURCE_CATALOG]
    out: dict[str, dict[str, Any]] = {}
    for sid in ids:
        saved = get_rotation_settings()["sources"].get(sid) or {}
        out[sid] = {
            "daily_limit": int(saved.get("daily_limit", DEFAULT_DAILY_LIMIT)),
            "default_est": int(saved.get("default_est", DEFAULT_EST)),
            "saved": dict(saved),
        }
    return {
        "defaults": {
            "daily_limit": DEFAULT_DAILY_LIMIT,
            "default_est": DEFAULT_EST,
        },
        "sources": out,
    }
