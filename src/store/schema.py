"""スキーマ関連: 起動時の辞書データ同期(PG移行後の残存職責)。

SQLite 時代の DDL 一括再実行(init_schema)・SCHEMA_VERSION 管理・
db-migrate チェイン(v3→v5)は PostgreSQL + Alembic 移行に伴い廃止
(docs/sqlite-pg-migration-plan.md D2)。スキーマ変更の正本は
``src/alembic/versions/`` 配下のリビジョン(適用は ``python3 src/cli.py
db-init`` = ``alembic upgrade head``)。本モジュールの残存職責は:

- ``sync_feature_dictionary``: 機能カテゴリ辞書(feature_categories 正本)と
  property_features.category 列の内容の起動時差分同期(データ同期であり
  スキーマ変更ではないため Alembic の管轄外)。辞書ハッシュの格納先は
  schema_meta テーブル(feature_dict_hash キーのみ。schema_version キーは
  alembic_version への一元化により廃止)。
"""

from __future__ import annotations

import sys
import time

import psycopg


def feature_dict_hash() -> str:
    """辞書の内容ハッシュ(feature_categories の正本から計算)。"""
    import hashlib

    from domain.feature_categories import (
        FEATURE_CATEGORIES,
        NON_FILTER_FEATURES,
        PARENT_CODES,
    )

    payload = repr(
        (
            sorted((c.code, c.label, c.include) for c in FEATURE_CATEGORIES),
            sorted(NON_FILTER_FEATURES),
            sorted(PARENT_CODES.items()),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sync_feature_dictionary(conn: psycopg.Connection) -> None:
    """起動時の辞書差分同期(決定 4 — 機能カテゴリ統一設計)。

    schema_meta の辞書ハッシュが不変ならスキップ。変更時は語彙ごとの
    category を再設定し、辞書から消えた code の行を NULL へ戻す。
    失敗方針は構造と分離(§4.2): ロック系エラーは 3 回リトライ →
    超過は警告ログで起動を継続し次回起動で再適用(同期スキップは検索が
    旧語彙へ戻るのみ)。
    """
    from domain.feature_categories import FEATURE_CATEGORIES

    h = feature_dict_hash()
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'feature_dict_hash'"
        ).fetchone()
    except psycopg.errors.UndefinedTable:
        return  # 未マイグレーション DB(db-init 未実行)—起動を妨げない
    if row and row[0] == h:
        return

    valid_codes = {c.code for c in FEATURE_CATEGORIES}
    for attempt in range(3):
        try:
            with conn.transaction():
                for cat in FEATURE_CATEGORIES:
                    ph = ",".join("%s" for _ in cat.include)
                    conn.execute(
                        "UPDATE property_features SET category = %s"
                        f" WHERE feature_name IN ({ph})"
                        " AND category IS DISTINCT FROM %s",
                        (cat.code, *cat.include, cat.code),
                    )
                ph = ",".join("%s" for _ in valid_codes)
                conn.execute(
                    "UPDATE property_features SET category = NULL"
                    f" WHERE category IS NOT NULL AND category NOT IN ({ph})",
                    tuple(valid_codes),
                )
                conn.execute(
                    """
                    INSERT INTO schema_meta(key, value) VALUES('feature_dict_hash', %s)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (h,),
                )
            conn.commit()
            return
        except psycopg.errors.DeadlockDetected:
            time.sleep(0.5)
        except psycopg.errors.LockNotAvailable:
            time.sleep(0.5)
    print(
        "warning: feature dictionary sync skipped (database busy) — "
        "will retry on next startup",
        file=sys.stderr,
    )
