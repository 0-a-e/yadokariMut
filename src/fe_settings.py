"""Frontend default settings persistence (v2 DB app_settings, key='fe_settings').

保存対象はフロントエンドの「デフォルト値」設定のみ(設計 doc map-layer-system-v2 §2):

    {"layers": {"<layerId>": {"defaultOpacity": 0.6, "clustering": false}},
     "global": {"pinClustering": true, "pinBalloonPermanent": false,
                "mapBackground": "black"}}

- 1キー1行JSONで app_settings に保存する (読み書きの共通実装は
  store.app_settings.JsonSettingsStore。null=削除の部分マージ契約も同参照。
  layers は id 付き二階層、global はフラットマップとして扱う)
- レイヤ実行時状態(現在透明度・並び順)は localStorage 側
- 契約型は frontend/src/lib/feSettings.ts の FeSettings と整合する
"""

from __future__ import annotations

from typing import Any, Optional

from store.app_settings import (
    JsonSettingsStore,
    validate_bool_or_null,
    validate_choice_or_null,
    validate_entry_id_string,
    validate_number_or_null,
)

_SETTINGS_KEY = "fe_settings"
_LAYER_OVERRIDE_KEYS = {"defaultOpacity", "clustering"}
_GLOBAL_KEYS = {"pinClustering", "pinBalloonPermanent", "mapBackground"}
# 最下レイヤ(基本地図)下に見える地図コンテナ背景色。black = 従来の #1a1a24
_MAP_BACKGROUND_CHOICES = ("black", "white")


def _validate_layer_entry_id(layer_id: Any) -> None:
    validate_entry_id_string(layer_id, max_len=64, label="layerId")


_store = JsonSettingsStore(
    _SETTINGS_KEY,
    ("layers", "global"),
    keyed=("layers",),
    allowed_keys={"layers": _LAYER_OVERRIDE_KEYS, "global": _GLOBAL_KEYS},
    validators={
        "layers": {
            "defaultOpacity": lambda v, where: validate_number_or_null(v, 0.0, 1.0, where),
            "clustering": validate_bool_or_null,
        },
        "global": {
            "pinClustering": validate_bool_or_null,
            "pinBalloonPermanent": validate_bool_or_null,
            "mapBackground": lambda v, where: validate_choice_or_null(
                v, _MAP_BACKGROUND_CHOICES, where
            ),
        },
    },
    entry_id_validator=_validate_layer_entry_id,
)


def get_fe_settings() -> dict:
    """Load saved FE default settings. Returns {"layers": {}, "global": {}} when unset."""
    return _store.load()


def save_fe_settings(update: Any) -> dict:
    """Partial-merge save. Returns the full settings after save.

    - update.layers.<id>.<key> = 値   → そのキーのみ上書き
    - update.layers.<id>.<key> = null → その保存済みキーを削除(カタログ既定へ戻す)
    - update.layers.<id> = null       → そのレイヤの保存全体を削除
    - update.global.<key> も同様(null で削除)

    不正な値は ValueError。呼び出し側(web_server)が HTTPException(400) にする。
    """
    return _store.save(update)
