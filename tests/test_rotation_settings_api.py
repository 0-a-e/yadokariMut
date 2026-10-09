#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API tests for /api/admin/rotation-settings (per-source rotation overrides)."""

import pytest


def test_get_rotation_settings_shape(client):
    res = client.get("/api/admin/rotation-settings")
    assert res.status_code == 200
    data = res.json()
    assert set(data.keys()) == {"defaults", "sources"}
    assert data["defaults"]["daily_limit"] == 500
    assert data["defaults"]["default_est"] == 60
    for sid in ("bratto", "unionmonthly"):
        src = data["sources"][sid]
        assert src["daily_limit"] == 500
        assert src["default_est"] == 60
        assert src["saved"] == {}


def test_post_then_get_reflects_override(client):
    res = client.post(
        "/api/admin/rotation-settings",
        json={"sources": {"bratto": {"daily_limit": 800, "default_est": 40}}},
    )
    assert res.status_code == 200
    data = client.get("/api/admin/rotation-settings").json()
    assert data["sources"]["bratto"]["daily_limit"] == 800
    assert data["sources"]["bratto"]["default_est"] == 40
    assert data["sources"]["bratto"]["saved"] == {
        "daily_limit": 800,
        "default_est": 40,
    }
    # 他ソースは無影響
    assert data["sources"]["unionmonthly"]["saved"] == {}


def test_post_null_resets_to_default(client):
    client.post(
        "/api/admin/rotation-settings",
        json={"sources": {"bratto": {"daily_limit": 800, "default_est": 40}}},
    )
    res = client.post(
        "/api/admin/rotation-settings",
        json={"sources": {"bratto": {"daily_limit": None}}},
    )
    assert res.status_code == 200
    data = client.get("/api/admin/rotation-settings").json()
    assert data["sources"]["bratto"]["daily_limit"] == 500
    assert data["sources"]["bratto"]["default_est"] == 40
    assert data["sources"]["bratto"]["saved"] == {"default_est": 40}


@pytest.mark.parametrize(
    "update",
    [
        {"sources": {"bratto": {"daily_limit": 0}}},
        {"sources": {"bratto": {"daily_limit": 10001}}},
        {"sources": {"bratto": {"default_est": 1.5}}},
        {"sources": {"bratto": {"daily_limit": "500"}}},
        {"sources": {"nosuchsource": {"daily_limit": 500}}},
    ],
)
def test_post_invalid_returns_400(client, update):
    res = client.post("/api/admin/rotation-settings", json=update)
    assert res.status_code == 400


def test_rotation_status_reflects_saved_override(client):
    """GET /api/admin/rotation の表示値も保存値を反映する。"""
    client.post(
        "/api/admin/rotation-settings",
        json={"sources": {"bratto": {"daily_limit": 800}}},
    )
    res = client.get("/api/admin/rotation")
    assert res.status_code == 200
    bratto = next(s for s in res.json()["sources"] if s["id"] == "bratto")
    assert bratto["daily_limit"] == 800
    unionmonthly = next(s for s in res.json()["sources"] if s["id"] == "unionmonthly")
    assert unionmonthly["daily_limit"] == 500
