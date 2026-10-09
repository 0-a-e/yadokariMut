"""app_settings テーブルへの 1 キー 1 行 JSON 設定の部分マージ永続化 (共通実装).

scrape_settings / rotation_settings / fe_settings の 3 モジュールで重複していた
以下を JsonSettingsStore に集約した:

- ``SELECT value_json FROM app_settings WHERE key = %s`` の読み込み
  (テーブル未作成 / 未保存 / 壊れ JSON はすべて「未保存」として既定形状を返す)
- ``INSERT ... ON CONFLICT(key) DO UPDATE`` の upsert
- psycopg.errors.UndefinedTable 吸収(未マイグレーション DB)
- null = 削除 (既定へ戻す) セマンティクスの部分マージ
- トップレベルコンテナ / エントリ id / パッチキー / 値のバリデーション

各設定モジュールは公開関数名を維持したまま本ストアへ委譲する。値の範囲検証
(秒数 / 件数 / 透明度等) は validators として注入する。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional

import psycopg

from store.pg import open_connection

# 値検証関数のシグネチャ: (value, where) -> None / 不正なら ValueError
ValueValidator = Callable[[Any, str], None]
# エントリ id 検証関数のシグネチャ: (entry_id) -> None / 不正なら ValueError
EntryIdValidator = Callable[[Any], None]


class JsonSettingsStore:
    """app_settings の 1 キー 1 行 JSON を部分マージで読み書きするストア.

    containers
        正規化時に保証するトップレベルの辞書コンテナ群。
        例: scrape/rotation は ``("sources",)``、fe は ``("layers", "global")``。

    keyed
        ``{<entry_id>: {<key>: value}}`` の二階層マップであるコンテナ (id 検証と
        エントリ単位の null 削除が効く)。keyed 外のコンテナは ``{<key>: value}``
        のフラットマップとして扱う (fe の ``global``)。

    allowed_keys / validators
        コンテナごとのパッチ許容キーと値検証関数 (key 順は宣言順 = 検証順)。

    entry_id_validator
        keyed コンテナのエントリ id 検証 (必須)。
    """

    def __init__(
        self,
        key: str,
        containers: tuple[str, ...],
        *,
        keyed: tuple[str, ...] = (),
        allowed_keys: Mapping[str, Iterable[str]],
        validators: Optional[Mapping[str, Mapping[str, ValueValidator]]] = None,
        entry_id_validator: Optional[EntryIdValidator] = None,
    ):
        if not containers:
            raise ValueError("containers must not be empty")
        unknown_keyed = set(keyed) - set(containers)
        if unknown_keyed:
            raise ValueError(
                f"keyed containers not in containers: {sorted(unknown_keyed)}"
            )
        unknown_allowed = set(allowed_keys) - set(containers)
        if unknown_allowed:
            raise ValueError(
                f"allowed_keys for unknown containers: {sorted(unknown_allowed)}"
            )
        for container in keyed:
            if entry_id_validator is None:
                raise ValueError(
                    f"keyed container {container!r} requires entry_id_validator"
                )

        self.key = key
        self.containers = tuple(containers)
        self._keyed = frozenset(keyed)
        self._allowed = {c: frozenset(v) for c, v in allowed_keys.items()}
        self._validators = {c: dict(v) for c, v in (validators or {}).items()}
        self._entry_id_validator = entry_id_validator

    # ----------------------------------------------------------------------
    # public API
    # ----------------------------------------------------------------------
    def load(self) -> dict:
        """Load saved settings. Returns the default shape when unset."""
        with open_connection() as conn:
            try:
                row = conn.execute(
                    "SELECT value_json FROM app_settings WHERE key = %s", (self.key,)
                ).fetchone()
            except psycopg.errors.UndefinedTable:
                # テーブル未作成(v2初期化前)でも未保存として扱う
                return self._empty()
            if not row:
                return self._empty()
            # value_json は jsonb(Phase 6b)なので psycopg が dict を返す
            data = row["value_json"]
            if not isinstance(data, dict):
                return self._empty()
            return self._normalize(data)

    def save(self, update: Any) -> dict:
        """Partial-merge save. Returns the full settings after save.

        - update.<container>.<id>.<key> = 値   → そのキーのみ上書き
        - update.<container>.<id>.<key> = null → その保存済みキーを削除(既定へ戻す)
        - update.<container>.<id> = null       → そのエントリの保存全体を削除

        不正な値は ValueError。呼び出し側(web_server)が HTTPException(400) にする。
        """
        self._validate_update(update)
        merged = self._merge(self.load(), update)

        with open_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO app_settings(key, value_json, updated_at) VALUES(%s, %s, %s)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        self.key,
                        json.dumps(merged, ensure_ascii=False),
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()
                return merged
            except Exception:
                conn.rollback()
                raise

    # ----------------------------------------------------------------------
    # shape
    # ----------------------------------------------------------------------
    def _empty(self) -> dict:
        return {container: {} for container in self.containers}

    def _normalize(self, data: Any) -> dict:
        """Guarantee the {container: {}} shape regardless of stored JSON."""
        if not isinstance(data, dict):
            data = {}
        out: dict[str, Any] = {}
        for container in self.containers:
            entries = (
                data.get(container) if isinstance(data.get(container), dict) else {}
            )
            if container in self._keyed:
                out[container] = {
                    str(k): dict(v) for k, v in entries.items() if isinstance(v, dict)
                }
            else:
                out[container] = dict(entries)
        return out

    # ----------------------------------------------------------------------
    # validation
    # ----------------------------------------------------------------------
    def _validate_update(self, update: Any) -> None:
        if not isinstance(update, dict):
            raise ValueError("update must be a JSON object")
        unknown = set(update.keys()) - set(self.containers)
        if unknown:
            raise ValueError(
                f"unknown keys: {sorted(unknown)}"
                f" (allowed: {', '.join(sorted(self.containers))})"
            )

        for container in self.containers:
            entries = update.get(container)
            if entries is None:
                continue
            if not isinstance(entries, dict):
                raise ValueError(f"{container} must be an object")
            if container in self._keyed:
                self._validate_keyed_entries(container, entries)
            else:
                self._validate_patch(container, entries, where=container)

    def _validate_keyed_entries(self, container: str, entries: dict) -> None:
        for entry_id, patch in entries.items():
            self._entry_id_validator(entry_id)
            if patch is None:
                continue
            if not isinstance(patch, dict):
                raise ValueError(f"{container}.{entry_id} must be an object or null")
            self._validate_patch(container, patch, where=f"{container}.{entry_id}")

    def _validate_patch(self, container: str, patch: dict, *, where: str) -> None:
        allowed = self._allowed.get(container, frozenset())
        unknown_keys = set(patch.keys()) - allowed
        if unknown_keys:
            raise ValueError(
                f"{where}: unknown keys {sorted(unknown_keys)}"
                f" (allowed: {sorted(allowed)})"
            )
        # 宣言順で検証 (エラー優先度が元実装と同一になる)
        for key, validator in (self._validators.get(container) or {}).items():
            if key in patch:
                validator(patch[key], f"{where}.{key}")

    # ----------------------------------------------------------------------
    # merge
    # ----------------------------------------------------------------------
    def _merge(self, current: dict, update: dict) -> dict:
        merged = self._normalize(current)
        for container in self.containers:
            entries_update = update.get(container)
            if not entries_update:
                continue
            if container in self._keyed:
                self._merge_keyed(merged[container], entries_update)
            else:
                self._merge_flat(merged[container], entries_update)
        return merged

    @staticmethod
    def _merge_keyed(target_map: dict, entries_update: dict) -> None:
        for entry_id, patch in entries_update.items():
            if patch is None:
                target_map.pop(entry_id, None)
                continue
            target = target_map.setdefault(entry_id, {})
            for key, value in patch.items():
                if value is None:
                    target.pop(key, None)
                else:
                    target[key] = value
            if not target:
                # 全キーが削除されたなら空エントリは残さない
                target_map.pop(entry_id, None)

    @staticmethod
    def _merge_flat(target: dict, entries_update: dict) -> None:
        for key, value in entries_update.items():
            if value is None:
                target.pop(key, None)
            else:
                target[key] = value


# ----------------------------------------------------------------------
# 共通バリデータ (設定 3 モジュールから集約)
# ----------------------------------------------------------------------
def known_source_ids() -> set[str]:
    """SOURCE_CATALOG 由来のソース id。読み込み失敗時は空(id 検証をスキップ)。"""
    try:
        from store.source_catalog import SOURCE_IDS

        return set(SOURCE_IDS)
    except Exception:
        return set()


def validate_source_id(
    source_id: Any, known_ids: set[str], *, max_len: int = 64, label: str = "sourceId"
) -> None:
    """keyed コンテナのソース id 検証 (scrape/rotation 共通)。"""
    if not isinstance(source_id, str) or not source_id:
        raise ValueError(f"{label} must be a non-empty string: {source_id!r}")
    if len(source_id) > max_len:
        raise ValueError(f"{label} too long (max {max_len}): {source_id[:20]}...")
    if known_ids and source_id not in known_ids:
        raise ValueError(f"unknown {label}: {source_id}")


def validate_entry_id_string(
    entry_id: Any, *, max_len: int = 64, label: str = "layerId"
) -> None:
    """カタログ非依存の自由 id (layerId 等) の検証。文字列種別と長さのみ。"""
    if not isinstance(entry_id, str) or not entry_id:
        raise ValueError(f"{label} must be a non-empty string: {entry_id!r}")
    if len(entry_id) > max_len:
        raise ValueError(f"{label} too long (max {max_len}): {entry_id[:20]}...")


def validate_number_or_null(
    value: Any, minimum: float, maximum: float, where: str
) -> None:
    """数値 (null 許容) の範囲検証。bool は数値として扱わない。"""
    if value is None:
        return
    # bool は int のサブクラスなので明示的に除外
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number in {minimum}..{maximum} or null")
    if not (minimum <= float(value) <= maximum):
        raise ValueError(f"{where} must be within {minimum}..{maximum}: {value}")


def validate_int_or_null(value: Any, minimum: int, maximum: int, where: str) -> None:
    """整数 (null 許容) の範囲検証。bool / 小数は無効。"""
    if value is None:
        return
    # bool は int のサブクラスなので明示的に除外。小数も件数として無効
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an integer in {minimum}..{maximum} or null")
    if not (minimum <= value <= maximum):
        raise ValueError(f"{where} must be within {minimum}..{maximum}: {value}")


def validate_bool_or_null(value: Any, where: str) -> None:
    """真偽値 (null 許容) の検証。"""
    if value is None:
        return
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be a boolean or null")


def validate_choice_or_null(
    value: Any, choices: Iterable[str], where: str
) -> None:
    """列挙文字列 (null 許容) の検証。"""
    if value is None:
        return
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{where} must be one of {sorted(choices)} or null")
