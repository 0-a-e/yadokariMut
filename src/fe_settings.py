"""Frontend default settings persistence (v2 DB app_settings, key='fe_settings').

保存対象はフロントエンドの「デフォルト値」設定のみ(設計 doc map-layer-system-v2 §2):

    {"layers": {"<layerId>": {"defaultOpacity": 0.6, "clustering": false}},
     "global": {"pinClustering": true}}

- 1キー1行JSONで app_settings に保存する
- POSTは部分マージ: 指定キーのみ上書き、null 送信でその保存済みキーを削除
  (カタログ既定へ戻す)。レイヤ実行時状態(現在透明度・並び順)は localStorage 側
- 契約型は frontend/src/lib/feSettings.ts の FeSettings と整合する
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

from store.repository import get_connection
from store.schema import init_schema

_SETTINGS_KEY = "fe_settings"
_LAYER_ID_MAX_LEN = 64
_LAYER_OVERRIDE_KEYS = {"defaultOpacity", "clustering"}
_GLOBAL_KEYS = {"pinClustering"}


def get_fe_settings(default_db_path: Optional[str] = None) -> dict:
    """Load saved FE default settings. Returns {"layers": {}, "global": {}} when unset."""
    conn = get_connection(default_db_path)
    try:
        try:
            row = conn.execute(
                "SELECT value_json FROM app_settings WHERE key = ?", (_SETTINGS_KEY,)
            ).fetchone()
        except sqlite3.OperationalError:
            # テーブル未作成(v2初期化前)でも未保存として扱う
            return _empty_settings()
        if not row:
            return _empty_settings()
        try:
            data = json.loads(row["value_json"])
        except (TypeError, ValueError):
            return _empty_settings()
        return _normalize(data)
    finally:
        conn.close()


def save_fe_settings(update: Any, default_db_path: Optional[str] = None) -> dict:
    """Partial-merge save. Returns the full settings after save.

    - update.layers.<id>.<key> = 値   → そのキーのみ上書き
    - update.layers.<id>.<key> = null → その保存済みキーを削除(カタログ既定へ戻す)
    - update.layers.<id> = null       → そのレイヤの保存全体を削除
    - update.global.<key> も同様(null で削除)

    不正な値は ValueError。呼び出し側(web_server)が HTTPException(400) にする。
    """
    _validate_update(update)
    merged = _merge_settings(_load_current(default_db_path), update)

    conn = get_connection(default_db_path)
    try:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at) VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (
                _SETTINGS_KEY,
                json.dumps(merged, ensure_ascii=False),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return merged
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ----------------------------------------------------------------------
# internals
# ----------------------------------------------------------------------
def _empty_settings() -> dict:
    return {"layers": {}, "global": {}}


def _normalize(data: Any) -> dict:
    """Guarantee the {"layers": {}, "global": {}} shape regardless of stored JSON."""
    if not isinstance(data, dict):
        return _empty_settings()
    layers = data.get("layers") if isinstance(data.get("layers"), dict) else {}
    glob = data.get("global") if isinstance(data.get("global"), dict) else {}
    return {
        "layers": {str(k): dict(v) for k, v in layers.items() if isinstance(v, dict)},
        "global": dict(glob),
    }


def _load_current(default_db_path: Optional[str]) -> dict:
    conn = get_connection(default_db_path)
    try:
        try:
            row = conn.execute(
                "SELECT value_json FROM app_settings WHERE key = ?", (_SETTINGS_KEY,)
            ).fetchone()
        except sqlite3.OperationalError:
            return _empty_settings()
        if not row:
            return _empty_settings()
        try:
            data = json.loads(row["value_json"])
        except (TypeError, ValueError):
            return _empty_settings()
        return _normalize(data)
    finally:
        conn.close()


def _validate_update(update: Any) -> None:
    if not isinstance(update, dict):
        raise ValueError("update must be a JSON object")
    unknown = set(update.keys()) - {"layers", "global"}
    if unknown:
        raise ValueError(f"unknown keys: {sorted(unknown)} (allowed: global, layers)")

    layers = update.get("layers")
    if layers is not None:
        if not isinstance(layers, dict):
            raise ValueError("layers must be an object")
        for layer_id, patch in layers.items():
            _validate_layer_id(layer_id)
            if patch is None:
                continue
            if not isinstance(patch, dict):
                raise ValueError(f"layers.{layer_id} must be an object or null")
            unknown_keys = set(patch.keys()) - _LAYER_OVERRIDE_KEYS
            if unknown_keys:
                raise ValueError(
                    f"layers.{layer_id}: unknown keys {sorted(unknown_keys)}"
                    f" (allowed: {sorted(_LAYER_OVERRIDE_KEYS)})"
                )
            if "defaultOpacity" in patch:
                _validate_default_opacity(patch["defaultOpacity"], f"layers.{layer_id}.defaultOpacity")
            if "clustering" in patch:
                _validate_bool_or_null(patch["clustering"], f"layers.{layer_id}.clustering")

    glob = update.get("global")
    if glob is not None:
        if not isinstance(glob, dict):
            raise ValueError("global must be an object")
        unknown_keys = set(glob.keys()) - _GLOBAL_KEYS
        if unknown_keys:
            raise ValueError(
                f"global: unknown keys {sorted(unknown_keys)} (allowed: {sorted(_GLOBAL_KEYS)})"
            )
        if "pinClustering" in glob:
            _validate_bool_or_null(glob["pinClustering"], "global.pinClustering")


def _validate_layer_id(layer_id: Any) -> None:
    if not isinstance(layer_id, str) or not layer_id:
        raise ValueError(f"layerId must be a non-empty string: {layer_id!r}")
    if len(layer_id) > _LAYER_ID_MAX_LEN:
        raise ValueError(
            f"layerId too long (max {_LAYER_ID_MAX_LEN}): {layer_id[:20]}..."
        )


def _validate_default_opacity(value: Any, where: str) -> None:
    if value is None:
        return
    # bool は int のサブクラスなので明示的に除外
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number in 0..1 or null")
    if not (0.0 <= float(value) <= 1.0):
        raise ValueError(f"{where} must be within 0..1: {value}")


def _validate_bool_or_null(value: Any, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be a boolean or null")


def _merge_settings(current: dict, update: dict) -> dict:
    merged = _normalize(current)

    layers_update = update.get("layers")
    if layers_update:
        for layer_id, patch in layers_update.items():
            if patch is None:
                merged["layers"].pop(layer_id, None)
                continue
            target = merged["layers"].setdefault(layer_id, {})
            for key, value in patch.items():
                if value is None:
                    target.pop(key, None)
                else:
                    target[key] = value
            if not target:
                # 全キーが削除されたなら空エントリは残さない
                merged["layers"].pop(layer_id, None)

    global_update = update.get("global")
    if global_update:
        for key, value in global_update.items():
            if value is None:
                merged["global"].pop(key, None)
            else:
                merged["global"][key] = value

    return merged
