#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for fe_settings (app_settings key='fe_settings' partial-merge persistence)."""

import json

import pytest


from helpers import isolated_db
from store.pg import open_connection  # noqa: F401 (COUNT 直クエリ検証用)
from fe_settings import get_fe_settings, save_fe_settings

LAYER_ID = "swale"


@pytest.fixture()
def db_path():
    """隔離 PG DSN(env YADOKARIMUT_PG_DSN を設定・baseline 適用済み)。"""
    with isolated_db("settings") as dsn:
        yield dsn


@pytest.fixture()
def _empty_db():
    """テーブル未作成(未マイグレーション)の空 PG DB に DSN を向ける。"""
    import os
    import uuid

    from helpers import TEST_DB_PREFIX, _admin_exec, dsn_for

    dbname = TEST_DB_PREFIX + "empty_" + uuid.uuid4().hex[:8]
    _admin_exec(f'CREATE DATABASE "{dbname}" TEMPLATE template0')
    old = os.environ.get("YADOKARIMUT_PG_DSN")
    os.environ["YADOKARIMUT_PG_DSN"] = dsn_for(dbname)
    yield dbname
    if old is None:
        os.environ.pop("YADOKARIMUT_PG_DSN", None)
    else:
        os.environ["YADOKARIMUT_PG_DSN"] = old
    _admin_exec(f'DROP DATABASE IF EXISTS "{dbname}"')


def _stored_row():
    from store.pg import open_connection

    with open_connection() as conn:
        return conn.execute(
            "SELECT value_json, updated_at FROM app_settings WHERE key = 'fe_settings'"
        ).fetchone()


def test_get_returns_empty_when_unset(db_path):
    assert get_fe_settings() == {"layers": {}, "global": {}}


def test_get_returns_empty_when_table_missing(_empty_db):
    # 未マイグレーション DB でも未保存として空を返す(エラーにしない)
    assert get_fe_settings() == {"layers": {}, "global": {}}


def test_save_partial_merge_then_get_reflects(db_path):
    saved = save_fe_settings(
        {"layers": {LAYER_ID: {"defaultOpacity": 0.6}}, "global": {"pinClustering": False}})
    assert saved == {
        "layers": {LAYER_ID: {"defaultOpacity": 0.6}},
        "global": {"pinClustering": False},
    }
    assert get_fe_settings() == saved

    # 部分マージ: 既存キーを壊さず別レイヤ/別キーを追加
    saved2 = save_fe_settings(
        {"layers": {LAYER_ID: {"clustering": True}, "flood_l1": {"defaultOpacity": 0.5}}})
    assert saved2 == {
        "layers": {
            LAYER_ID: {"defaultOpacity": 0.6, "clustering": True},
            "flood_l1": {"defaultOpacity": 0.5},
        },
        "global": {"pinClustering": False},
    }
    assert get_fe_settings() == saved2


def test_save_global_balloon_permanent_partial_merge_and_null_delete(db_path):
    # pinBalloonPermanent: クラスタリングと独立したglobalキーとして部分マージ
    saved = save_fe_settings({"global": {"pinClustering": False, "pinBalloonPermanent": True}})
    assert saved == {
        "layers": {},
        "global": {"pinClustering": False, "pinBalloonPermanent": True},
    }

    # 既存globalキーを壊さず片方のみ更新
    saved2 = save_fe_settings({"global": {"pinBalloonPermanent": False}})
    assert saved2["global"] == {"pinClustering": False, "pinBalloonPermanent": False}

    # null で削除(未指定=既定falseへ戻す)
    saved3 = save_fe_settings({"global": {"pinBalloonPermanent": None}})
    assert saved3["global"] == {"pinClustering": False}


def test_save_global_map_background_partial_merge_and_null_delete(db_path):
    # mapBackground: 黒/白の列挙値を持つglobalキーとして部分マージ
    saved = save_fe_settings(
        {"global": {"pinClustering": False, "mapBackground": "white"}})
    assert saved == {
        "layers": {},
        "global": {"pinClustering": False, "mapBackground": "white"},
    }

    # 既存globalキーを壊さず片方のみ更新(もう片方の選択肢 black も有効)
    saved2 = save_fe_settings({"global": {"mapBackground": "black"}})
    assert saved2["global"] == {"pinClustering": False, "mapBackground": "black"}

    # null で削除(未指定='black' へ戻す)
    saved3 = save_fe_settings({"global": {"mapBackground": None}})
    assert saved3["global"] == {"pinClustering": False}


def test_save_updates_existing_key_in_place(db_path):
    save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.3}}})
    saved = save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.8}}})
    assert saved == {"layers": {LAYER_ID: {"defaultOpacity": 0.8}}, "global": {}}


def test_null_deletes_saved_key_and_layer(db_path):
    save_fe_settings(
        {
            "layers": {LAYER_ID: {"defaultOpacity": 0.6, "clustering": True}},
            "global": {"pinClustering": False},
        })

    # キー単位の null 削除(カタログ既定へ戻す)
    saved = save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": None}}})
    assert saved["layers"][LAYER_ID] == {"clustering": True}

    # global も同様
    saved = save_fe_settings({"global": {"pinClustering": None}})
    assert saved["global"] == {}

    # レイヤ全体の null 削除
    saved = save_fe_settings({"layers": {LAYER_ID: None}})
    assert saved["layers"] == {}

    assert get_fe_settings() == {"layers": {}, "global": {}}


def test_null_delete_on_absent_key_is_noop(db_path):
    saved = save_fe_settings(
        {"layers": {LAYER_ID: {"defaultOpacity": None}}, "global": {"pinClustering": None}})
    assert saved == {"layers": {}, "global": {}}


def test_empty_update_returns_full_settings(db_path):
    save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.6}}})
    assert save_fe_settings({}) == {
        "layers": {LAYER_ID: {"defaultOpacity": 0.6}},
        "global": {},
    }


def test_save_persists_single_json_row_with_updated_at(db_path):
    save_fe_settings({"global": {"pinClustering": True}})
    row = _stored_row()
    assert row is not None
    assert row["value_json"] == {"layers": {}, "global": {"pinClustering": True}}
    assert row["updated_at"]

    with open_connection() as _c:
        count = _c.execute(
        "SELECT COUNT(*) FROM app_settings WHERE key = 'fe_settings'"
        ).fetchone()[0]
    assert count == 1


def test_save_works_without_precreated_table(_empty_db):
    # PG 移行後の契約: スキーマ保証は Alembic の管轄で、未マイグレーション DB
    # への save は UndefinedTable となる(旧 SQLite の save 時 init_schema 廃止)
    import psycopg
    import pytest as _pytest

    with _pytest.raises(psycopg.errors.UndefinedTable):
        save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.3}}})


@pytest.mark.parametrize(
    "update",
    [
        {"layers": {LAYER_ID: {"defaultOpacity": 1.5}}},  # 範囲外
        {"layers": {LAYER_ID: {"defaultOpacity": -0.1}}},  # 範囲外
        {"layers": {LAYER_ID: {"defaultOpacity": "0.6"}}},  # 文字列
        {"layers": {LAYER_ID: {"defaultOpacity": True}}},  # bool は数値扱いしない
        {"layers": {LAYER_ID: {"clustering": "yes"}}},  # bool 以外
        {"global": {"pinClustering": 1}},  # bool 以外(int)
        {"global": {"pinBalloonPermanent": "yes"}},  # bool 以外(文字列)
        {"global": {"mapBackground": "gray"}},  # 列挙外の値
        {"global": {"mapBackground": 1}},  # 非文字列
        {"layers": {LAYER_ID: {"unknownKey": True}}},  # レイヤの未知キー
        {"global": {"unknownKey": True}},  # global の未知キー
        {"unknown": {}},  # トップレベルの未知キー
        {"layers": {"a" * 65: {"defaultOpacity": 0.6}}},  # layerId 長すぎ
        {"layers": {123: {"defaultOpacity": 0.6}}},  # layerId 非文字列
        {"layers": {LAYER_ID: "0.6"}},  # レイヤパッチがオブジェクトでない
        {"layers": "x"},  # layers がオブジェクトでない
        "not-an-object",  # update 自体がオブジェクトでない
        None,
    ],
)
def test_invalid_update_raises_value_error(db_path, update):
    with pytest.raises(ValueError):
        save_fe_settings(update)
    # 不正値では保存されない
    assert get_fe_settings() == {"layers": {}, "global": {}}


def test_boundary_opacity_values_are_valid(db_path):
    saved = save_fe_settings(
        {"layers": {"a": {"defaultOpacity": 0}, "b": {"defaultOpacity": 1}}})
    assert saved["layers"] == {"a": {"defaultOpacity": 0}, "b": {"defaultOpacity": 1}}
