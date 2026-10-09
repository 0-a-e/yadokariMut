#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rotation_settings (app_settings key='rotation_settings' partial-merge persistence)."""

import json

import pytest


from helpers import isolated_db
from rotation_settings import (
    DEFAULT_DAILY_LIMIT,
    DEFAULT_EST,
    effective_rotation_settings,
    get_rotation_settings,
    resolve_effective_limits,
    save_rotation_settings,
)
from web.rotation_jobs import DEFAULT_ROTATION_SOURCES

SID = "bratto"


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


def _stored_json():
    from store.pg import open_connection

    with open_connection() as conn:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = 'rotation_settings'"
        ).fetchone()
        return row["value_json"] if row else None


def test_get_returns_empty_when_unset(db_path):
    assert get_rotation_settings() == {"sources": {}}


def test_get_returns_empty_when_table_missing(_empty_db):
    # 未マイグレーション DB でも未保存として空を返す(エラーにしない)
    assert get_rotation_settings() == {"sources": {}}


def test_save_partial_merge_then_get_reflects(db_path):
    saved = save_rotation_settings(
        {"sources": {SID: {"daily_limit": 800, "default_est": 40}}})
    assert saved == {"sources": {SID: {"daily_limit": 800, "default_est": 40}}}
    assert get_rotation_settings() == saved
    stored = _stored_json()
    assert stored["sources"][SID]["daily_limit"] == 800


def test_save_second_source_keeps_first(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}})
    saved = save_rotation_settings(
        {"sources": {"unionmonthly": {"default_est": 30}}})
    assert saved["sources"][SID] == {"daily_limit": 800}
    assert saved["sources"]["unionmonthly"] == {"default_est": 30}


def test_save_null_key_deletes_only_that_key(db_path):
    save_rotation_settings(
        {"sources": {SID: {"daily_limit": 800, "default_est": 40}}})
    saved = save_rotation_settings({"sources": {SID: {"daily_limit": None}}})
    assert saved["sources"][SID] == {"default_est": 40}


def test_save_null_source_deletes_whole_entry(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}})
    saved = save_rotation_settings({"sources": {SID: None}})
    assert saved == {"sources": {}}


def test_save_empty_patch_does_not_create_entry(db_path):
    saved = save_rotation_settings({"sources": {SID: {"daily_limit": None}}})
    assert saved == {"sources": {}}


@pytest.mark.parametrize(
    "update",
    [
        # unknown top-level key
        {"global": {}},
        # sources not an object
        {"sources": []},
        # unknown patch key
        {"sources": {SID: {"pages": 3}}},
        # patch not an object
        {"sources": {SID: 4}},
        # bool is not an integer
        {"sources": {SID: {"daily_limit": True}}},
        # non-integer
        {"sources": {SID: {"daily_limit": "500"}}},
        {"sources": {SID: {"default_est": 60.5}}},
        # 0 は予算枯渇扱いになるため無効
        {"sources": {SID: {"daily_limit": 0}}},
        # out of range
        {"sources": {SID: {"daily_limit": 10001}}},
        {"sources": {SID: {"default_est": -1}}},
        # unknown source id
        {"sources": {"nosuchsource": {"daily_limit": 500}}},
        # bad source id type
        {"sources": {"": {"daily_limit": 500}}},
        # not an object at all
        "daily_limit",
    ],
)
def test_save_validation_errors(db_path, update):
    with pytest.raises(ValueError):
        save_rotation_settings(update)
    assert get_rotation_settings() == {"sources": {}}


@pytest.mark.parametrize("value", [1, 10000])
def test_save_accepts_range_boundaries(db_path, value):
    saved = save_rotation_settings({"sources": {SID: {"daily_limit": value}}})
    assert saved["sources"][SID]["daily_limit"] == value


def test_resolve_effective_limits_defaults_when_unset(db_path):
    limits = resolve_effective_limits(SID)
    assert limits == {"daily_limit": DEFAULT_DAILY_LIMIT, "default_est": DEFAULT_EST}


def test_resolve_effective_limits_saved_wins(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}})
    limits = resolve_effective_limits(SID)
    assert limits == {"daily_limit": 800, "default_est": DEFAULT_EST}


def test_resolve_effective_limits_unknown_source_falls_back_to_defaults(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}})
    limits = resolve_effective_limits("nosuchsource")
    assert limits == {"daily_limit": DEFAULT_DAILY_LIMIT, "default_est": DEFAULT_EST}


def test_effective_rotation_settings_shape_and_precedence(db_path):
    save_rotation_settings(
        {"sources": {SID: {"daily_limit": 800, "default_est": 40}}})
    eff = effective_rotation_settings()
    assert set(eff.keys()) == {"defaults", "sources"}
    assert eff["defaults"] == {
        "daily_limit": DEFAULT_DAILY_LIMIT,
        "default_est": DEFAULT_EST,
    }
    # SOURCE_CATALOG 由来のソース id が全て出力される
    assert set(eff["sources"].keys()) >= set(DEFAULT_ROTATION_SOURCES)
    assert eff["sources"][SID]["daily_limit"] == 800
    assert eff["sources"][SID]["default_est"] == 40
    assert eff["sources"][SID]["saved"] == {"daily_limit": 800, "default_est": 40}
    # 未保存ソースは既定値
    assert eff["sources"]["unionmonthly"]["daily_limit"] == DEFAULT_DAILY_LIMIT
    assert eff["sources"]["unionmonthly"]["saved"] == {}
