#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API tests for /api/admin/scrape-settings (per-source scrape overrides)."""

import sqlite3

import pytest
from fastapi.testclient import TestClient


from store.schema import init_schema


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """tmp DB に向けた TestClient。web_server は request 時に DB パス解決する。"""
    db = str(tmp_path / "yadokari_mut_v2.db")
    conn = sqlite3.connect(db)
    try:
        init_schema(conn)
    finally:
        conn.close()
    monkeypatch.setenv("YADOKARIMUT_V2_DB_PATH", db)
    from web_server import app

    return TestClient(app)


def test_get_scrape_settings_shape(client):
    res = client.get("/api/admin/scrape-settings")
    assert res.status_code == 200
    data = res.json()
    assert set(data.keys()) == {"defaults", "sources"}
    assert data["defaults"]["delay_seconds"] > 0
    assert data["defaults"]["cooldown_seconds"] >= 0
    for sid in ("bratto", "unionmonthly"):
        src = data["sources"][sid]
        assert isinstance(src["delay_seconds"], (int, float))
        assert isinstance(src["cooldown_seconds"], (int, float))
        assert src["saved"] == {}


def test_post_then_get_reflects_override(client):
    res = client.post(
        "/api/admin/scrape-settings",
        json={"sources": {"bratto": {"delay_seconds": 4, "cooldown_seconds": 900}}},
    )
    assert res.status_code == 200
    data = client.get("/api/admin/scrape-settings").json()
    assert data["sources"]["bratto"]["delay_seconds"] == 4.0
    assert data["sources"]["bratto"]["cooldown_seconds"] == 900.0
    assert data["sources"]["bratto"]["saved"] == {
        "delay_seconds": 4.0,
        "cooldown_seconds": 900.0,
    }
    # 他ソースは無影響
    assert data["sources"]["unionmonthly"]["saved"] == {}


def test_post_null_key_resets_to_default(client):
    defaults = client.get("/api/admin/scrape-settings").json()["defaults"]
    client.post(
        "/api/admin/scrape-settings",
        json={"sources": {"bratto": {"delay_seconds": 4, "cooldown_seconds": 900}}},
    )
    res = client.post(
        "/api/admin/scrape-settings",
        json={"sources": {"bratto": {"delay_seconds": None}}},
    )
    assert res.status_code == 200
    data = client.get("/api/admin/scrape-settings").json()
    assert data["sources"]["bratto"]["delay_seconds"] == defaults["delay_seconds"]
    # cooldown の保存は残る
    assert data["sources"]["bratto"]["cooldown_seconds"] == 900.0


def test_post_invalid_value_returns_400(client):
    res = client.post(
        "/api/admin/scrape-settings",
        json={"sources": {"bratto": {"delay_seconds": 999}}},
    )
    assert res.status_code == 400
    assert "delay_seconds" in res.json()["detail"]


def test_post_unknown_source_returns_400(client):
    res = client.post(
        "/api/admin/scrape-settings",
        json={"sources": {"nosuchsource": {"delay_seconds": 4}}},
    )
    assert res.status_code == 400
    assert "nosuchsource" in res.json()["detail"]
