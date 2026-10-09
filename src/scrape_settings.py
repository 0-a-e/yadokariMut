"""Per-source scrape overrides persistence (v2 DB app_settings, key='scrape_settings').

保存対象はプロバイダ別スクレイプ実行パラメタの「上書き値」のみ:

    {"sources": {"bratto": {"delay_seconds": 4.0, "cooldown_seconds": 900.0}}}

- 1キー1行JSONで app_settings に保存する (読み書きの共通実装は
  store.app_settings.JsonSettingsStore。null=削除の部分マージ契約も同参照)
- 実行時は run_scrape_task が apply_to_source_config() でアダプタ設定へ
  マージする。優先順位: 保存値 > config.json sources.<id> > コード既定
  (API の run 時 delay 指定はさらに優先)
- delay_seconds は各リクエスト前の間隔(sources.base)、cooldown_seconds は
  制限検知時のクールダウン秒(sources.http.settings)に反映される
"""

from __future__ import annotations

from typing import Any, Optional

from store.app_settings import (
    JsonSettingsStore,
    known_source_ids,
    validate_number_or_null,
    validate_source_id,
)

_SETTINGS_KEY = "scrape_settings"
_SOURCE_KEYS = {"delay_seconds", "cooldown_seconds"}

# sources.base の既定値と同期させること
_DELAY_MIN, _DELAY_MAX = 0.5, 30.0
# 制限時クールダウン: 0 で無効化。env 既定(600s)の上書き用
_COOLDOWN_MIN, _COOLDOWN_MAX = 0.0, 7200.0


def _validate_source_entry_id(source_id: Any) -> None:
    validate_source_id(source_id, known_source_ids())


_store = JsonSettingsStore(
    _SETTINGS_KEY,
    ("sources",),
    keyed=("sources",),
    allowed_keys={"sources": _SOURCE_KEYS},
    validators={
        "sources": {
            "delay_seconds": lambda v, where: validate_number_or_null(
                v, _DELAY_MIN, _DELAY_MAX, where
            ),
            "cooldown_seconds": lambda v, where: validate_number_or_null(
                v, _COOLDOWN_MIN, _COOLDOWN_MAX, where
            ),
        }
    },
    entry_id_validator=_validate_source_entry_id,
)


def get_scrape_settings() -> dict:
    """Load saved per-source overrides. Returns {"sources": {}} when unset."""
    return _store.load()


def save_scrape_settings(update: Any) -> dict:
    """Partial-merge save. Returns the full settings after save.

    - update.sources.<id>.<key> = 値   → そのキーのみ上書き
    - update.sources.<id>.<key> = null → その保存済みキーを削除(既定へ戻す)
    - update.sources.<id> = null       → そのソースの保存全体を削除

    不正な値は ValueError。呼び出し側(web_server)が HTTPException(400) にする。
    """
    return _store.save(update)


def apply_to_source_config(
    source_id: str, src_cfg: dict | None
) -> dict:
    """Merge saved overrides into an adapter config dict (non-mutating).

    保存済みキーが config.json 由来の src_cfg を上書きする。未保存キーは
    src_cfg の値(config.json/未設定)のまま。run 時の明示指定(delay パラメタ)
    は呼び出し側がこの関数の後で上書きする想定。
    """
    saved = get_scrape_settings()["sources"].get(source_id) or {}
    out = dict(src_cfg or {})
    for key in _SOURCE_KEYS:
        if key in saved:
            out[key] = saved[key]
    return out


def effective_source_settings() -> dict:
    """Admin UI 用: ソース別の保存済み上書き + 実効値 + 既定値を返す。

    実効値 = 保存値 > config.json sources.<id> > コード既定
    (cooldown のコード既定は load_http_settings() の env/config 解決結果)。
    """
    from store.source_catalog import SOURCE_CATALOG, load_app_config

    saved = get_scrape_settings()["sources"]
    sources_cfg = load_app_config().get("sources") or {}

    from sources.base import DEFAULT_DELAY_SECONDS
    from sources.http.settings import load_http_settings

    default_delay = float(DEFAULT_DELAY_SECONDS)
    default_cooldown = float(load_http_settings().cooldown_seconds)

    ids = [entry["id"] for entry in SOURCE_CATALOG]
    out: dict[str, dict[str, Any]] = {}
    for sid in ids:
        cfg = sources_cfg.get(sid) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        over = saved.get(sid) or {}
        out[sid] = {
            "delay_seconds": float(over.get("delay_seconds", cfg.get("delay_seconds", default_delay))),
            "cooldown_seconds": float(
                over.get("cooldown_seconds", cfg.get("cooldown_seconds", default_cooldown))
            ),
            "saved": dict(over),
        }
    return {
        "defaults": {
            "delay_seconds": default_delay,
            "cooldown_seconds": default_cooldown,
        },
        "sources": out,
    }
