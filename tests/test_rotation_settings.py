#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rotation_settings (app_settings key='rotation_settings' partial-merge persistence)."""

import json
import sqlite3

import pytest


from rotation_settings import (
    DEFAULT_DAILY_LIMIT,
    DEFAULT_EST,
    effective_rotation_settings,
    get_rotation_settings,
    resolve_effective_limits,
    save_rotation_settings,
)
from store.schema import init_schema

SID = "bratto"


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


def _stored_json(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = 'rotation_settings'"
        ).fetchone()
        return row["value_json"] if row else None
    finally:
        conn.close()


def test_get_returns_empty_when_unset(db_path):
    assert get_rotation_settings(db_path) == {"sources": {}}


def test_get_returns_empty_when_table_missing(tmp_path):
    # init_schema 未実行の DB でも未保存として空を返す(エラーにしない)
    path = str(tmp_path / "fresh.db")
    conn = sqlite3.connect(path)
    conn.close()
    assert get_rotation_settings(path) == {"sources": {}}


def test_save_partial_merge_then_get_reflects(db_path):
    saved = save_rotation_settings(
        {"sources": {SID: {"daily_limit": 800, "default_est": 40}}}, db_path
    )
    assert saved == {"sources": {SID: {"daily_limit": 800, "default_est": 40}}}
    assert get_rotation_settings(db_path) == saved
    stored = json.loads(_stored_json(db_path))
    assert stored["sources"][SID]["daily_limit"] == 800


def test_save_second_source_keeps_first(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}}, db_path)
    saved = save_rotation_settings(
        {"sources": {"unionmonthly": {"default_est": 30}}}, db_path
    )
    assert saved["sources"][SID] == {"daily_limit": 800}
    assert saved["sources"]["unionmonthly"] == {"default_est": 30}


def test_save_null_key_deletes_only_that_key(db_path):
    save_rotation_settings(
        {"sources": {SID: {"daily_limit": 800, "default_est": 40}}}, db_path
    )
    saved = save_rotation_settings({"sources": {SID: {"daily_limit": None}}}, db_path)
    assert saved["sources"][SID] == {"default_est": 40}


def test_save_null_source_deletes_whole_entry(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}}, db_path)
    saved = save_rotation_settings({"sources": {SID: None}}, db_path)
    assert saved == {"sources": {}}


def test_save_empty_patch_does_not_create_entry(db_path):
    saved = save_rotation_settings({"sources": {SID: {"daily_limit": None}}}, db_path)
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
        save_rotation_settings(update, db_path)
    assert get_rotation_settings(db_path) == {"sources": {}}


@pytest.mark.parametrize("value", [1, 10000])
def test_save_accepts_range_boundaries(db_path, value):
    saved = save_rotation_settings({"sources": {SID: {"daily_limit": value}}}, db_path)
    assert saved["sources"][SID]["daily_limit"] == value


def test_resolve_effective_limits_defaults_when_unset(db_path):
    limits = resolve_effective_limits(SID, db_path)
    assert limits == {"daily_limit": DEFAULT_DAILY_LIMIT, "default_est": DEFAULT_EST}


def test_resolve_effective_limits_saved_wins(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}}, db_path)
    limits = resolve_effective_limits(SID, db_path)
    assert limits == {"daily_limit": 800, "default_est": DEFAULT_EST}


def test_resolve_effective_limits_unknown_source_falls_back_to_defaults(db_path):
    save_rotation_settings({"sources": {SID: {"daily_limit": 800}}}, db_path)
    limits = resolve_effective_limits("nosuchsource", db_path)
    assert limits == {"daily_limit": DEFAULT_DAILY_LIMIT, "default_est": DEFAULT_EST}


def test_effective_rotation_settings_shape_and_precedence(db_path):
    save_rotation_settings(
        {"sources": {SID: {"daily_limit": 800, "default_est": 40}}}, db_path
    )
    eff = effective_rotation_settings(db_path)
    assert set(eff.keys()) == {"defaults", "sources"}
    assert eff["defaults"] == {
        "daily_limit": DEFAULT_DAILY_LIMIT,
        "default_est": DEFAULT_EST,
    }
    # SOURCE_CATALOG 由来のソース id が全て出力される
    assert set(eff["sources"].keys()) >= {SID, "unionmonthly"}
    assert eff["sources"][SID]["daily_limit"] == 800
    assert eff["sources"][SID]["default_est"] == 40
    assert eff["sources"][SID]["saved"] == {"daily_limit": 800, "default_est": 40}
    # 未保存ソースは既定値
    assert eff["sources"]["unionmonthly"]["daily_limit"] == DEFAULT_DAILY_LIMIT
    assert eff["sources"]["unionmonthly"]["saved"] == {}
