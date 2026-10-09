#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建物ショートリスト(ブックマーク)機構のテスト.

- POST /api/buildings/{building_id}/shortlist (saved/none・404・422)
- BuildingProperties への shortlist_status / shortlist_comment 配信
- saved_only の建物意味論(建物saved OR 部屋saved≥1)
- U3: 建物saved は全部屋 inactive でも配信を貫通
- merge_buildings の状態移行 / split は元側保持
- KML の stBuildingSaved / db_stats / identity dry-run レポート
"""

import json
import sqlite3

import pytest

from domain.models import PropertyFeature
from helpers import make_tokyo_draft
from store.building_identity import merge_buildings, run_identity_batch, split_building
from store.repository import Repository, open_connection

ADDR_A = "東京都渋谷区神宮前1-2-3"  # 建物 A: 2 部屋
ADDR_B = "東京都渋谷区神宮前9-9-9"  # 建物 B: 1 部屋


def _room(eid, *, address=ADDR_A, lat=35.66, lng=139.70, rent=5000, title=None):
    draft = make_tokyo_draft(
        eid,
        address=address,
        lat=lat,
        lng=lng,
        rent_current_yen=rent,
        title=title if title is not None else f"ユニオンマンスリーB1 {eid}",
    )
    draft.price_plans[0].management_yen = 0
    return draft


@pytest.fixture()
def seeded(client):
    """建物 A 2 部屋 + 建物 B 1 部屋を upsert し building_id を解決して返す."""
    repo = Repository()
    a_101 = repo.upsert_property(
        _room("b1-101", rent=6000, title="ユニオンマンスリーB1 101")
    )
    a_102 = repo.upsert_property(
        _room("b1-102", rent=5000, title="ユニオンマンスリーB1 102")
    )
    b_901 = repo.upsert_property(
        _room("b1-901", address=ADDR_B, lat=35.67, lng=139.71, rent=4000,
              title="ユニオンマンスリーB2 901")
    )
    with open_connection() as conn:
        bids = {
            int(r["id"]): int(r["building_id"])
            for r in conn.execute(
                "SELECT id, building_id FROM properties"
                f" WHERE id IN ({a_101},{a_102},{b_901})"
            )
        }
    return {
        "a_101": a_101,
        "a_102": a_102,
        "b_901": b_901,
        "bid_a": bids[a_101],
        "bid_b": bids[b_901],
    }


def _features_by_id(payload: dict) -> dict[int, dict]:
    return {f["properties"]["id"]: f["properties"] for f in payload["features"]}


class TestBuildingShortlistApi:
    def test_post_saved_and_none_roundtrip(self, client, seeded):
        bid = seeded["bid_a"]
        res = client.post(
            f"/api/buildings/{bid}/shortlist", json={"status": "saved", "comment": "候補建物"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body == {
            "status": "success",
            "building_id": bid,
            "shortlist_status": "saved",
        }

        # GeoJSON feature に状態とメモが載る
        props = _features_by_id(_bulk(client))[bid]
        assert props["shortlist_status"] == "saved"
        assert props["shortlist_comment"] == "候補建物"

        # none で解除(null に戻る)
        res = client.post(f"/api/buildings/{bid}/shortlist", json={"status": "none"})
        assert res.status_code == 200
        props = _features_by_id(_bulk(client))[bid]
        assert props["shortlist_status"] is None
        assert props["shortlist_comment"] is None

    def test_post_not_found(self, client, seeded):
        res = client.post("/api/buildings/99999/shortlist", json={"status": "saved"})
        assert res.status_code == 404

    def test_post_rejects_room_statuses(self, client, seeded):
        """建物側は当面 saved/none のみ(hide/reject は 422)。"""
        for bad in ("hide", "reject"):
            res = client.post(
                f"/api/buildings/{seeded['bid_a']}/shortlist", json={"status": bad}
            )
            assert res.status_code == 422, bad

    def test_comment_not_clobbered_by_null(self, client, seeded):
        """comment 未指定の再保存では既存メモが維持される(部屋と対称)。"""
        bid = seeded["bid_a"]
        client.post(f"/api/buildings/{bid}/shortlist",
                    json={"status": "saved", "comment": "初回メモ"})
        client.post(f"/api/buildings/{bid}/shortlist", json={"status": "saved"})
        props = _features_by_id(_bulk(client))[bid]
        assert props["shortlist_comment"] == "初回メモ"


class TestSavedOnlyBuildingSemantics:
    def test_saved_only_matches_building_saved_or_room_saved(self, client, seeded):
        """建物saved(部屋saved 0)も部屋saved≥1 の建物もヒット(承認 U1)。"""
        bid_a, bid_b = seeded["bid_a"], seeded["bid_b"]
        # 建物 A: 建物側のみ saved。建物 B: 部屋 901 のみ saved
        client.post(f"/api/buildings/{bid_a}/shortlist", json={"status": "saved"})
        client.post(
            f"/api/properties/{seeded['b_901']}/shortlist",
            json={"status": "saved"},
        )
        res = client.get("/api/buildings/geojson?saved_only=true")
        assert res.status_code == 200
        got = set(_features_by_id(res.json()))
        assert got == {bid_a, bid_b}

    def test_building_saved_survives_all_inactive_units(self, client, seeded):
        """U3: 建物saved の建物は全部屋 inactive でも配信される(units は空可)."""
        bid_a = seeded["bid_a"]
        client.post(f"/api/buildings/{bid_a}/shortlist", json={"status": "saved"})
        # 建物 A の全部屋を inactive 化(shortlist 未登録のまま)
        with open_connection() as conn:
            conn.execute(
                f"UPDATE properties SET is_active = FALSE WHERE id IN"
                f" ({seeded['a_101']},{seeded['a_102']})"
            )
            conn.commit()

        props = _features_by_id(_bulk(client)).get(bid_a)
        assert props is not None, "建物saved の建物は inactive 化後も配信される"
        assert props["units"] == []

        # 建物saved が無い建物 B は通常どおり配信される(active 部屋あり)
        assert seeded["bid_b"] in _features_by_id(_bulk(client))


class TestIdentityMergeSplit:
    def test_merge_carries_building_shortlist(self, client, seeded):
        """merge_buildings: b 側の状態は CASCADE で消えず a へ移行する。"""
        bid_a, bid_b = seeded["bid_a"], seeded["bid_b"]
        client.post(f"/api/buildings/{bid_b}/shortlist",
                    json={"status": "saved", "comment": "B のメモ"})
        with open_connection() as conn:
            merge_buildings(conn, bid_a, bid_b)
        with open_connection() as conn:
            rows = conn.execute(
                "SELECT building_id, status, comment FROM building_shortlists"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["building_id"] == bid_a
        assert rows[0]["status"] == "saved"
        assert rows[0]["comment"] == "B のメモ"

    def test_merge_newer_updated_at_wins(self, client, seeded):
        """両方 saved の場合は updated_at が新しい方を採用・メモは連結。"""
        bid_a, bid_b = seeded["bid_a"], seeded["bid_b"]
        with open_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO building_shortlists (building_id, status, comment, updated_at)"
                    " VALUES (%s, 'saved', %s, %s)",
                    [(bid_a, "A のメモ", "2026-10-01T00:00:00"),
                     (bid_b, "B のメモ", "2026-10-02T00:00:00")],
                )
            conn.commit()
            merge_buildings(conn, bid_a, bid_b)
        with open_connection() as conn:
            row = conn.execute(
                "SELECT status, comment FROM building_shortlists WHERE building_id = %s",
                (bid_a,),
            ).fetchone()
        assert row["comment"] == "A のメモ\nB のメモ"
        assert row["status"] == "saved"

    def test_split_keeps_state_on_origin(self, client, seeded):
        bid_a = seeded["bid_a"]
        client.post(f"/api/buildings/{bid_a}/shortlist", json={"status": "saved"})
        with open_connection() as conn:
            new_id = split_building(conn, bid_a, [seeded["a_102"]])
        with open_connection() as conn:
            bids = [
                int(r["building_id"])
                for r in conn.execute("SELECT building_id FROM building_shortlists")
            ]
        assert bids == [bid_a], "状態は元建物側に保持(新建物には付かない)"
        assert new_id != bid_a

    def test_identity_batch_reports_building_shortlist_rows(self, client, seeded):
        client.post(f"/api/buildings/{seeded['bid_a']}/shortlist",
                    json={"status": "saved"})
        with open_connection() as conn:
            report = run_identity_batch(conn, apply=False)
        assert report["building_shortlists_rows"] == 1


class TestKmlAndStats:
    def test_kml_building_saved_style(self, client, seeded):
        """部屋自身の未保存 + 建物saved → stBuildingSaved(部屋 saved が優先)。"""
        bid_a = seeded["bid_a"]
        client.post(f"/api/buildings/{bid_a}/shortlist", json={"status": "saved"})
        # FE 経路と同じ ids 指定エクスポート(応答は KML 生文字列)
        res = client.post(
            "/api/export/kml",
            json={"ids": [seeded["a_101"], seeded["a_102"]]},
        )
        assert res.status_code == 200
        kml = res.text
        assert kml.count("#stBuildingSaved") == 2  # 建物 A の両部屋(styleUrl 参照)

        # 部屋 saved は stSaved 優先
        client.post(
            f"/api/properties/{seeded['a_101']}/shortlist", json={"status": "saved"}
        )
        res = client.post(
            "/api/export/kml", json={"ids": [seeded["a_101"], seeded["a_102"]]}
        )
        kml = res.text
        assert kml.count("#stBuildingSaved") == 1  # 102 のみ
        assert "#stSaved" in kml  # 101

    def test_db_stats_includes_building_shortlist(self, client, seeded):
        client.post(f"/api/buildings/{seeded['bid_a']}/shortlist",
                    json={"status": "saved"})
        stats = Repository().db_stats()
        assert stats["building_shortlist"] == {"saved": 1}
        # 部屋側集計は従来どおり shortlist キー
        assert stats["shortlist"] == {}


def _bulk(client, query: str = "") -> dict:
    res = client.get(f"/api/buildings/geojson{query}")
    assert res.status_code == 200
    return res.json()
