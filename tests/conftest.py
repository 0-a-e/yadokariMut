"""tests 共通設定: 隔離DBの安全網と環境変数の復元 + 共有 fixture (M13・PostgreSQL版).

- テンプレート DB (alembic baseline 適用済み) をセッション冒頭で1回作成し、
  tmp_v2_db / ScopedDb はそこから CREATE DATABASE ... TEMPLATE で隔離 DB を複製する
- autouse fixture で YADOKARIMUT_PG_DSN をテスト単位で退避/復元する
  (unittest.TestCase ベースのテストにも適用される)
- tmp_v2_db / client は API 系テスト向けの共有 fixture
  (旧 test_scrape_settings_api.py 等の完全コピペ3複製を集約)
"""

import atexit
import os

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_db

# 旧 SQLite conftest と同じ安全網: モジュール側で DSN 設定を忘れたテストも
# 本番既定 DSN(property)ではなくセッション用の隔離 DB へ向く。
# pytest は test モジュールの import 前に conftest を読むためここで効く。
_FALLBACK_SCOPE = None


def _drop_fallback() -> None:
    from helpers import _admin_exec

    if _FALLBACK_SCOPE:
        _admin_exec(f'DROP DATABASE IF EXISTS "{_FALLBACK_SCOPE}"')


def _fallback_db() -> str:
    global _FALLBACK_SCOPE
    if _FALLBACK_SCOPE is None:
        import uuid

        from helpers import TEMPLATE_DB, TEST_DB_PREFIX, _admin_exec, dsn_for, ensure_template_db

        ensure_template_db()
        dbname = TEST_DB_PREFIX + "fallback_" + uuid.uuid4().hex[:8]
        _admin_exec(f'CREATE DATABASE "{dbname}" TEMPLATE "{TEMPLATE_DB}"')
        _FALLBACK_SCOPE = dbname
        atexit.register(_drop_fallback)
    return dsn_for(_FALLBACK_SCOPE)


os.environ.setdefault("YADOKARIMUT_PG_DSN", _fallback_db())


@pytest.fixture(autouse=True)
def _restore_db_env():
    old = os.environ.get("YADOKARIMUT_PG_DSN")
    # テスト実行中は per-call 接続を使う(プールは DSN を固定化するため)
    old_pool = os.environ.get("YADOKARIMUT_PG_POOL")
    os.environ.pop("YADOKARIMUT_PG_POOL", None)
    yield
    if old is None:
        os.environ.pop("YADOKARIMUT_PG_DSN", None)
    else:
        os.environ["YADOKARIMUT_PG_DSN"] = old
    if old_pool is None:
        os.environ.pop("YADOKARIMUT_PG_POOL", None)
    else:
        os.environ["YADOKARIMUT_PG_POOL"] = old_pool


@pytest.fixture()
def tmp_v2_db(monkeypatch):
    """alembic baseline 適用済みの隔離 PG DB を作り、YADOKARIMUT_PG_DSN を向ける.

    web_server / api_queries / Repository は呼び出し毎に env を読むため、
    本 fixture 以降の処理はすべて隔離 DB に向く。DSN を返す。
    """
    with isolated_db("conftest") as dsn:
        monkeypatch.setenv("YADOKARIMUT_PG_DSN", dsn)
        yield dsn


@pytest.fixture()
def client(tmp_v2_db):
    """tmp DB に向けた TestClient。web_server は request 時に DSN を解決する。"""
    from web_server import app

    return TestClient(app)
