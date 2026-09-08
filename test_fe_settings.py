#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for fe_settings (app_settings key='fe_settings' partial-merge persistence)."""

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from fe_settings import get_fe_settings, save_fe_settings
from store.schema import init_schema

LAYER_ID = "swale"


@pytest.fixture()
def db_path(tmp_path):
    """v2 DB を tmp_path に作り、スキーマを初期化する。"""
    path = str(tmp_path / "yadokari_mut_v2.db")
    conn = sqlite3.connect(path)
    try:
        init_schema(conn)
    finally:
        conn.close()
    return path


def _stored_row(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT value_json, updated_at FROM app_settings WHERE key = 'fe_settings'"
        ).fetchone()
    finally:
        conn.close()


def test_get_returns_empty_when_unset(db_path):
    assert get_fe_settings(db_path) == {"layers": {}, "global": {}}


def test_get_returns_empty_when_table_missing(tmp_path):
    # init_schema 未実行の DB でも未保存として空を返す(エラーにしない)
    path = str(tmp_path / "fresh.db")
    conn = sqlite3.connect(path)
    conn.close()
    assert get_fe_settings(path) == {"layers": {}, "global": {}}


def test_save_partial_merge_then_get_reflects(db_path):
    saved = save_fe_settings(
        {"layers": {LAYER_ID: {"defaultOpacity": 0.6}}, "global": {"pinClustering": False}},
        db_path,
    )
    assert saved == {
        "layers": {LAYER_ID: {"defaultOpacity": 0.6}},
        "global": {"pinClustering": False},
    }
    assert get_fe_settings(db_path) == saved

    # 部分マージ: 既存キーを壊さず別レイヤ/別キーを追加
    saved2 = save_fe_settings(
        {"layers": {LAYER_ID: {"clustering": True}, "flood_l1": {"defaultOpacity": 0.5}}},
        db_path,
    )
    assert saved2 == {
        "layers": {
            LAYER_ID: {"defaultOpacity": 0.6, "clustering": True},
            "flood_l1": {"defaultOpacity": 0.5},
        },
        "global": {"pinClustering": False},
    }
    assert get_fe_settings(db_path) == saved2


def test_save_updates_existing_key_in_place(db_path):
    save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.3}}}, db_path)
    saved = save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.8}}}, db_path)
    assert saved == {"layers": {LAYER_ID: {"defaultOpacity": 0.8}}, "global": {}}


def test_null_deletes_saved_key_and_layer(db_path):
    save_fe_settings(
        {
            "layers": {LAYER_ID: {"defaultOpacity": 0.6, "clustering": True}},
            "global": {"pinClustering": False},
        },
        db_path,
    )

    # キー単位の null 削除(カタログ既定へ戻す)
    saved = save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": None}}}, db_path)
    assert saved["layers"][LAYER_ID] == {"clustering": True}

    # global も同様
    saved = save_fe_settings({"global": {"pinClustering": None}}, db_path)
    assert saved["global"] == {}

    # レイヤ全体の null 削除
    saved = save_fe_settings({"layers": {LAYER_ID: None}}, db_path)
    assert saved["layers"] == {}

    assert get_fe_settings(db_path) == {"layers": {}, "global": {}}


def test_null_delete_on_absent_key_is_noop(db_path):
    saved = save_fe_settings(
        {"layers": {LAYER_ID: {"defaultOpacity": None}}, "global": {"pinClustering": None}},
        db_path,
    )
    assert saved == {"layers": {}, "global": {}}


def test_empty_update_returns_full_settings(db_path):
    save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.6}}}, db_path)
    assert save_fe_settings({}, db_path) == {
        "layers": {LAYER_ID: {"defaultOpacity": 0.6}},
        "global": {},
    }


def test_save_persists_single_json_row_with_updated_at(db_path):
    save_fe_settings({"global": {"pinClustering": True}}, db_path)
    row = _stored_row(db_path)
    assert row is not None
    assert json.loads(row["value_json"]) == {"layers": {}, "global": {"pinClustering": True}}
    assert row["updated_at"]

    count = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM app_settings WHERE key = 'fe_settings'"
    ).fetchone()[0]
    assert count == 1


def test_save_works_without_precreated_table(tmp_path):
    # init_schema は save 側でも冪等に保証される
    path = str(tmp_path / "fresh.db")
    conn = sqlite3.connect(path)
    conn.close()
    saved = save_fe_settings({"layers": {LAYER_ID: {"defaultOpacity": 0.3}}}, path)
    assert saved == {"layers": {LAYER_ID: {"defaultOpacity": 0.3}}, "global": {}}
    assert get_fe_settings(path) == saved


@pytest.mark.parametrize(
    "update",
    [
        {"layers": {LAYER_ID: {"defaultOpacity": 1.5}}},  # 範囲外
        {"layers": {LAYER_ID: {"defaultOpacity": -0.1}}},  # 範囲外
        {"layers": {LAYER_ID: {"defaultOpacity": "0.6"}}},  # 文字列
        {"layers": {LAYER_ID: {"defaultOpacity": True}}},  # bool は数値扱いしない
        {"layers": {LAYER_ID: {"clustering": "yes"}}},  # bool 以外
        {"global": {"pinClustering": 1}},  # bool 以外(int)
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
        save_fe_settings(update, db_path)
    # 不正値では保存されない
    assert get_fe_settings(db_path) == {"layers": {}, "global": {}}


def test_boundary_opacity_values_are_valid(db_path):
    saved = save_fe_settings(
        {"layers": {"a": {"defaultOpacity": 0}, "b": {"defaultOpacity": 1}}}, db_path
    )
    assert saved["layers"] == {"a": {"defaultOpacity": 0}, "b": {"defaultOpacity": 1}}
