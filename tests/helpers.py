"""tests 共有ヘルパ: PropertyDraft ファクトリと隔離DBスコープ (PostgreSQL).

隔離方式は「テンプレート DB からの複製」(docs/sqlite-pg-migration-plan.md E2):
alembic upgrade head 済みの ``yadokari_test_template`` を1セッション1回作成し、
テスト/クラスごとに ``CREATE DATABASE ... TEMPLATE`` で複製して
``YADOKARIMUT_PG_DSN`` を差し替える。旧 SQLite 時代の tmp ファイル+env 差し替え
(ScopedDb/isolated_db)と同じ使用感(session 単位・関数単位)を維持する。
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

import psycopg

from domain.models import PricePlan, PropertyDraft

TEST_DB_PREFIX = "yadokari_test_"
TEMPLATE_DB = TEST_DB_PREFIX + "template"


def _base_dsn() -> str:
    """テスト用 PG のベース DSN(env または compose 既定)。"""
    from store.pg import resolve_dsn

    return os.environ.get("YADOKARIMUT_PG_DSN") or resolve_dsn()


def dsn_for(dbname: str) -> str:
    """ベース DSN の database 部分だけ差し替える。"""
    parts = urlsplit(_base_dsn())
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def _admin_exec(sql: str) -> None:
    """postgres メンテナンス DB に対する autocommit 実行(CREATE/DROP DATABASE 用)。"""
    with psycopg.connect(dsn_for("postgres"), autocommit=True, options="-c timezone=Asia/Tokyo") as conn:
        conn.execute(sql)


_template_ready = False


def ensure_template_db() -> str:
    """テンプレート DB(alembic baseline 適用済み)を用意し DSN を返す。

    プロセスで初回呼び出し時のみ drop & recreate する(1 pytest セッション =
    1 コード状態のため再作成は不要)。ベースラインリビジョンを変えた際は
    テンプレートを手動で消すか新しいセッションを立てればよい。
    """
    global _template_ready
    if _template_ready:
        return dsn_for(TEMPLATE_DB)
    _drop_db(TEMPLATE_DB)
    _admin_exec(f'CREATE DATABASE "{TEMPLATE_DB}" TEMPLATE template0')
    old = os.environ.get("YADOKARIMUT_PG_DSN")
    os.environ["YADOKARIMUT_PG_DSN"] = dsn_for(TEMPLATE_DB)
    try:
        from store.migrations import upgrade_head

        upgrade_head()
    finally:
        if old is None:
            os.environ.pop("YADOKARIMUT_PG_DSN", None)
        else:
            os.environ["YADOKARIMUT_PG_DSN"] = old
    _template_ready = True
    return dsn_for(TEMPLATE_DB)


def _drop_db(dbname: str) -> None:
    with psycopg.connect(dsn_for("postgres"), autocommit=True, options="-c timezone=Asia/Tokyo") as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE datname = %s AND pid <> pg_backend_pid()",
            (dbname,),
        )
    _admin_exec(f'DROP DATABASE IF EXISTS "{dbname}"')


def make_draft(
    external_id: str,
    *,
    source_site: str = "fakesite",
    entity_type: str = "room",
    title: Optional[str] = None,
    detail_url: Optional[str] = None,
    prefecture_name: Optional[str] = "東京都",
    prefecture_slug: Optional[str] = None,
    is_active: bool = True,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    price_plans: Any = (),
    campaigns: Any = (),
    **extra: Any,
) -> PropertyDraft:
    """テスト用の PropertyDraft を組み立てる.

    未指定フィールドの既定は旧 _draft 系ヘルパの最頻値に合わせる
    (title=f"物件 {external_id}", detail_url=f"https://example.test/{external_id}/",
    prefecture_slug="tokyo")。明示的に None 以外を渡した場合はその値を優先する。
    その他のフィールド (municipality, contract_fee_yen など) は extra から
    PropertyDraft にそのまま渡る。
    """
    return PropertyDraft(
        source_site=source_site,
        external_id=external_id,
        entity_type=entity_type,
        title=title if title is not None else f"物件 {external_id}",
        detail_url=(
            detail_url
            if detail_url is not None
            else f"https://example.test/{external_id}/"
        ),
        prefecture_name=prefecture_name,
        prefecture_slug=(
            prefecture_slug if prefecture_slug is not None else "tokyo"
        ),
        is_active=is_active,
        address=address,
        lat=lat,
        lng=lng,
        price_plans=list(price_plans),
        campaigns=list(campaigns),
        **extra,
    )


def make_tokyo_draft(
    external_id: str,
    *,
    source_site: str = "fakesite",
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    rent_current_yen: int = 5000,
    municipality: Optional[str] = "渋谷区",
    address: Optional[str] = "東京都渋谷区神宮前1-2-3",
    is_active: bool = True,
    title: Optional[str] = None,
    **extra: Any,
) -> PropertyDraft:
    """渋谷区神宮前・PricePlan(short) 付き PropertyDraft ファクトリ (M13).

    旧 _draft 群 (test_web_api.py / test_geojson_export.py / test_geojson_stream.py /
    test_analysis_api.py / test_export_kml_api.py) の最頻既定に合わせた定型:

    - address = 東京都渋谷区神宮前1-2-3 (municipality = 渋谷区)
    - price_plans = PricePlan(plan_key="short", 30〜89日, per_day, rent_current_yen)
    - title / detail_url / prefecture 系は make_draft 既定に委譲

    lat / lng / rent_current_yen / source_site / municipality 等は引数で上書きする。
    旧実装間で lat/lng・rent・municipality の既定に微差があるため、既存テストの
    _draft を置き換える場合は生成値が完全同一になる引数の組み合わせに限ること。
    """
    return make_draft(
        external_id,
        source_site=source_site,
        lat=lat,
        lng=lng,
        municipality=municipality,
        address=address,
        is_active=is_active,
        title=title,
        price_plans=[
            PricePlan(
                plan_key="short",
                plan_name="ショット",
                duration_min_days=30,
                duration_max_days=89,
                presentation_unit="per_day",
                rent_current_yen=rent_current_yen,
            )
        ],
        **extra,
    )


def insert_snapshot(
    conn: psycopg.Connection,
    property_id: int,
    scraped_at: str,
    value: Optional[int],
    is_active: bool = True,
) -> None:
    """property_snapshots への直 INSERT ヘルパ (M13).

    upsert 時に自動生成されるスナップショットを消した後、検証用の価格系列を
    手で置くための最小 INSERT (旧 test_analysis_api.py._snap 相当)。
    """
    conn.execute(
        "INSERT INTO property_snapshots "
        "(property_id, scraped_at, is_active, catalog_rent_per_day_yen) "
        "VALUES (%s, %s, %s, %s)",
        (property_id, scraped_at, is_active, value),
    )


class ScopedDb:
    """unittest の setUp / setUpClass から1行で隔離DBを張る (PG テンプレート複製).

    with 文をまたがない unittest での利用を想定し、close() で環境変数を
    旧値へ復元する。dsn 属性で接続先を取得できる。
    """

    def __init__(self, label: str):
        ensure_template_db()
        self.dbname = TEST_DB_PREFIX + uuid.uuid4().hex[:12]
        _admin_exec(f'CREATE DATABASE "{self.dbname}" TEMPLATE "{TEMPLATE_DB}"')
        self._old = os.environ.get("YADOKARIMUT_PG_DSN")
        self.dsn = dsn_for(self.dbname)
        os.environ["YADOKARIMUT_PG_DSN"] = self.dsn
        _live_scopes.add(self.dbname)

    def close(self) -> None:
        if self._old is None:
            os.environ.pop("YADOKARIMUT_PG_DSN", None)
        else:
            os.environ["YADOKARIMUT_PG_DSN"] = self._old
        if self.dbname in _live_scopes:
            _live_scopes.discard(self.dbname)
            _drop_db(self.dbname)


_live_scopes: set[str] = set()


def _drop_live_scopes_at_exit() -> None:
    """close 忘れの隔離 DB をセッション終了時に掃除(安全網)。"""
    for dbname in list(_live_scopes):
        try:
            _drop_db(dbname)
        except Exception:
            pass


import atexit  # noqa: E402

atexit.register(_drop_live_scopes_at_exit)


@contextmanager
def isolated_db(label: str) -> Iterator[str]:
    """ScopedDb の contextmanager 版。yield で DSN を渡す."""
    scope = ScopedDb(label)
    try:
        yield scope.dsn
    finally:
        scope.close()


def fetch_property_row(repo, property_id: int) -> dict | None:
    """tests 用: properties 行 1 件を直接 SELECT(Repository.get_property 削除に伴う代替・決定 13)。"""
    conn = repo.connect()
    try:
        row = conn.execute(
            "SELECT * FROM properties WHERE id = %s", (property_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch_child_rows(repo, property_id: int, table: str, order: str = "") -> list[dict]:
    """tests 用: 子テーブル行を直接 SELECT(price_plans 等の行取り出しヘルパ)。"""
    conn = repo.connect()
    try:
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM {table} WHERE property_id = %s{order}",
                (property_id,),
            )
        ]
    finally:
        conn.close()
