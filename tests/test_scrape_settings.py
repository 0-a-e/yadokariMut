#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scrape_settings (app_settings key='scrape_settings' partial-merge persistence)."""

import json

import pytest


from helpers import isolated_db
from scrape_settings import (
    apply_to_source_config,
    effective_source_settings,
    get_scrape_settings,
    save_scrape_settings,
)

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
            "SELECT value_json FROM app_settings WHERE key = 'scrape_settings'"
        ).fetchone()
        return row["value_json"] if row else None


def test_get_returns_empty_when_unset(db_path):
    assert get_scrape_settings() == {"sources": {}}


def test_get_returns_empty_when_table_missing(_empty_db):
    # 未マイグレーション DB でも未保存として空を返す(エラーにしない)
    assert get_scrape_settings() == {"sources": {}}


def test_save_partial_merge_then_get_reflects(db_path):
    saved = save_scrape_settings(
        {"sources": {SID: {"delay_seconds": 4.0, "cooldown_seconds": 900}}})
    assert saved == {"sources": {SID: {"delay_seconds": 4.0, "cooldown_seconds": 900.0}}}
    assert get_scrape_settings() == saved
    stored = _stored_json()
    assert stored["sources"][SID]["delay_seconds"] == 4.0


def test_save_second_source_keeps_first(db_path):
    save_scrape_settings({"sources": {SID: {"delay_seconds": 4.0}}})
    saved = save_scrape_settings(
        {"sources": {"unionmonthly": {"cooldown_seconds": 1200}}})
    assert saved["sources"][SID] == {"delay_seconds": 4.0}
    assert saved["sources"]["unionmonthly"] == {"cooldown_seconds": 1200.0}


def test_save_null_key_deletes_only_that_key(db_path):
    save_scrape_settings(
        {"sources": {SID: {"delay_seconds": 4.0, "cooldown_seconds": 900}}})
    saved = save_scrape_settings({"sources": {SID: {"delay_seconds": None}}})
    assert saved["sources"][SID] == {"cooldown_seconds": 900.0}


def test_save_null_source_deletes_whole_entry(db_path):
    save_scrape_settings({"sources": {SID: {"delay_seconds": 4.0}}})
    saved = save_scrape_settings({"sources": {SID: None}})
    assert saved == {"sources": {}}


def test_save_empty_patch_does_not_create_entry(db_path):
    saved = save_scrape_settings({"sources": {SID: {"delay_seconds": None}}})
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
        # bool is not a number
        {"sources": {SID: {"delay_seconds": True}}},
        # non-number
        {"sources": {SID: {"delay_seconds": "4"}}},
        # out of range
        {"sources": {SID: {"delay_seconds": 0.1}}},
        {"sources": {SID: {"delay_seconds": 31}}},
        {"sources": {SID: {"cooldown_seconds": -1}}},
        {"sources": {SID: {"cooldown_seconds": 7201}}},
        # unknown source id
        {"sources": {"nosuchsource": {"delay_seconds": 4}}},
        # bad source id type
        {"sources": {"": {"delay_seconds": 4}}},
        # not an object at all
        "delay",
    ],
)
def test_save_validation_errors(db_path, update):
    with pytest.raises(ValueError):
        save_scrape_settings(update)
    assert get_scrape_settings() == {"sources": {}}


def test_apply_to_source_config_saved_wins_over_config_json(db_path):
    save_scrape_settings({"sources": {SID: {"delay_seconds": 4.0}}})
    out = apply_to_source_config(SID, {"delay_seconds": 2.0, "base_url": "x"})
    assert out == {"delay_seconds": 4.0, "base_url": "x"}


def test_apply_to_source_config_without_saved_keeps_config_json(db_path):
    out = apply_to_source_config(
        SID, {"delay_seconds": 1.5, "cooldown_seconds": 300})
    assert out == {"delay_seconds": 1.5, "cooldown_seconds": 300}


def test_apply_to_source_config_no_config_no_saved(db_path):
    assert apply_to_source_config(SID, None) == {}


def test_apply_to_source_config_non_target_source_untouched(db_path):
    save_scrape_settings({"sources": {SID: {"delay_seconds": 4.0}}})
    out = apply_to_source_config(
        "unionmonthly", {"delay_seconds": 2.0})
    assert out == {"delay_seconds": 2.0}


def test_effective_source_settings_precedence(db_path, monkeypatch, tmp_path):
    # config.json 由来の sources.<id> を差し込む
    import store.source_catalog as sc

    monkeypatch.setattr(
        sc,
        "load_app_config",
        lambda: {
            "sources": {
                SID: {"delay_seconds": 1.0, "cooldown_seconds": 300},
                "unionmonthly": {},
            }
        },
    )
    save_scrape_settings({"sources": {SID: {"delay_seconds": 4.0}}})

    eff = effective_source_settings()
    assert eff["sources"][SID]["delay_seconds"] == 4.0  # 保存値 > config.json
    assert eff["sources"][SID]["cooldown_seconds"] == 300.0  # config.json > 既定
    assert eff["sources"][SID]["saved"] == {"delay_seconds": 4.0}
    # 保存も config.json も無いソースはコード既定
    assert eff["sources"]["unionmonthly"]["delay_seconds"] > 0
    assert eff["sources"]["unionmonthly"]["saved"] == {}
    assert eff["defaults"]["delay_seconds"] > 0
    assert eff["defaults"]["cooldown_seconds"] >= 0


def test_adapter_config_applies_delay_and_cooldown():
    # base.py が config の cooldown_seconds を http settings へ反映すること
    from sources.unionmonthly import UnionMonthlyAdapter

    adapter = UnionMonthlyAdapter({"delay_seconds": 3.5, "cooldown_seconds": 900})
    assert adapter.delay == 3.5
    assert adapter.http.settings.cooldown_seconds == 900.0

    default_adapter = UnionMonthlyAdapter({})
    assert default_adapter.http.settings.cooldown_seconds > 0
