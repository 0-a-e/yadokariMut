"""PostgreSQL 接続基盤 (SQLite→PG移行・docs/sqlite-pg-migration-plan.md §3.1)。

全ての DB アクセスは本モジュールの ``open_connection`` / ``connect`` を通る
(旧 ``store.repository.get_connection`` の後継・choke point はここに一本化)。

- ドライバ: psycopg 3 (同期)。``?`` ではなく ``%s`` プレースホルダ。
- 行ファクトリ: ``compat_row`` — sqlite3.Row 互換の dict サブクラス
  (``row[0]`` 位置アクセスと ``row["col"]`` 名前アクセスの両方が動く。
  旧コードの ``fetchone()[0]`` / ``row["id"]`` / ``dict(row)`` を全部無修正で
  通すための移行互換層)。
- トランザクション: autocommit=False(既定)。SELECT も暗黙トランザクションを張るが、
  per-call 接続は close 時に未 commit なら自動 rollback されるため読み取りは安全。
  明示 commit は呼び出し側(Repository)が行う従来方式を維持。
- 接続プール: 本番のみ ``YADOKARIMUT_PG_POOL=1`` で有効化(min 1 / max 8・D5)。
  開発・テストは per-call 接続(旧 SQLite と同型。DSN 差し替えテストとの相性優先)。
- DSN: ``YADOKARIMUT_PG_DSN`` 環境変数。未設定時はローカル compose 既定
  (127.0.0.1:5433/property)へフォールバック。
- セッション TZ = Asia/Tokyo 固定(Phase 6c・D8)。時刻列は naive JST 文字列
  (naive isoformat)で書き込まれるため、解釈 TZ を JST に固定しないと
  timestamptz 化で 9 時間ズレる。読み取りは JST の aware datetime が返る。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection
from psycopg_pool import ConnectionPool

DSN_ENV = "YADOKARIMUT_PG_DSN"
POOL_ENV = "YADOKARIMUT_PG_POOL"

# ローカル compose (docker-compose.yml db サービス) の既定。
DEFAULT_DSN = "postgresql://yadokari:yadokari-mut@127.0.0.1:5433/property"

_pool: ConnectionPool | None = None


def compat_row(cursor: psycopg.Cursor) -> Any:
    """sqlite3.Row 互換行ファクトリ(名前アクセス + 位置アクセス + 値イテレーション)。

    - ``row["col"]`` / ``row.get("col")`` — dict として動作(旧 dict(row) 変換も無修正)
    - ``row[0]`` — 位置アクセス(SELECT 句の並び順。``fetchone()[0]`` の COUNT 系や
      旧 sqlite3.Row コードを無修正で通す)
    - ``for v in row`` / ``tuple(row)``
      — 値のイテレーション(sqlite3.Row と同じ・dict のキー反復ではない)
    """
    fields = [d.name for d in cursor.description or []]

    class _Row(dict):
        __slots__ = ()

        def __getitem__(self, key):  # type: ignore[override]
            if isinstance(key, int):
                return dict.__getitem__(self, fields[key])
            return dict.__getitem__(self, key)

        def __iter__(self):  # type: ignore[override]
            return iter(self.values())

        def __eq__(self, other):  # type: ignore[override]
            if isinstance(other, (list, tuple)):
                return list(self.values()) == list(other)
            return dict.__eq__(self, other)

        __hash__ = None  # type: ignore[assignment]

    def make(values: list[Any]) -> _Row:
        row = _Row(zip(fields, values))
        return row

    return make


def resolve_dsn() -> str:
    """DSN を解決する唯一の窓口(テストは env 差し替えで上書き)。"""
    return os.environ.get(DSN_ENV) or DEFAULT_DSN


def pool_enabled() -> bool:
    return os.environ.get(POOL_ENV, "").lower() == "1"


# セッション TZ 固定(D8): naive JST 文字列パラメータの解釈と SELECT 返却を
# Asia/Tokyo に統一する(PG サーバー既定は UTC のため明示指定が必須)。
_CONN_OPTIONS = "-c timezone=Asia/Tokyo"


def _kwargs() -> dict:
    return {"row_factory": compat_row, "autocommit": False, "options": _CONN_OPTIONS}


def get_pool() -> ConnectionPool:
    """本番用の共有プール(初回呼び出しで生成・DSN は生成時に固定)。

    テストで DSN を差し替える場合はプールを無効化(per-call 接続)して使う。
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=resolve_dsn(),
            min_size=1,
            max_size=8,
            kwargs=_kwargs(),
            open=True,
        )
    return _pool


def close_pool() -> None:
    """アプリ終了時の後始末(pool 未生成なら何もしない)。"""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def connect(dsn: str | None = None) -> Connection:
    """生コネクションを返す(テスト・移行ツール等の自前管理向け)。"""
    return psycopg.connect(dsn or resolve_dsn(), **_kwargs())


@contextmanager
def open_connection(dsn: str | None = None) -> Iterator[Connection]:
    """close 保証付き接続の共通入口(旧 repository.open_connection の後継)。

    プール有効時は ``pool.connection()``(返却時に未 commit なら自動 rollback)、
    無効時は per-call 接続(close 時に同様に破棄)。commit/rollback は呼び出し側
    が明示的に行う(旧挙動のまま)。
    """
    if dsn is None and pool_enabled():
        with get_pool().connection() as conn:
            yield conn
        return
    conn = connect(dsn)
    try:
        yield conn
    finally:
        conn.close()
