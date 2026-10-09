#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建物単位 GeoJSON API (/api/buildings/geojson[/stream]) のテスト.

docs/building-aggregation-design.md §6.1 の配信契約を固定する:
- 1 Feature = 1 建物 + units 配列 (同一住所の複数部屋が 1 建物に集約)
- NDJSON ストリームは meta → feature×N → end の行契約 (単位は建物数)
- 既存の部屋単位 /api/geojson は無変更 (1 部屋 = 1 Feature のまま)
- required_features は「条件を満たす部屋を 1 つ以上持つ建物」でヒット
"""

import json

import pytest

from domain.models import PropertyFeature
from helpers import make_tokyo_draft
from store.repository import Repository

ADDR_A = "東京都渋谷区神宮前1-2-3"  # 建物 A: 2 部屋
ADDR_B = "東京都渋谷区神宮前9-9-9"  # 建物 B: 1 部屋


def _room(eid, *, address=ADDR_A, lat=35.66, lng=139.70, rent=5000, title=None,
          features=(), **extra):
    """make_tokyo_draft から建物集約テスト用の PropertyDraft を組む.

    **extra は make_tokyo_draft 経由で PropertyDraft へ素通しする
    (floor_number / orientation_deg 等の列を個別テストで注入するため)。
    """
    draft = make_tokyo_draft(
        eid,
        address=address,
        lat=lat,
        lng=lng,
        rent_current_yen=rent,
        title=title if title is not None else f"ユニオンマンスリーB1 {eid}",
        features=list(features),
        **extra,
    )
    # 30日総額 (min_plan_total) は管理費日額が確定しないと None になるため
    # テストでは 0 円を明示する (決定 11 の None 透過仕様)
    draft.price_plans[0].management_yen = 0
    return draft


@pytest.fixture()
def seeded(client):
    """建物 A (ADDR_A) 2 部屋 + 建物 B (ADDR_B) 1 部屋を upsert して id を返す."""
    repo = Repository()
    return {
        "a_101": repo.upsert_property(
            _room(
                "b1-101",
                rent=6000,
                title="ユニオンマンスリーB1 101",
                features=[PropertyFeature(feature_name="エレベーター", category="elevator")],
            )
        ),
        "a_102": repo.upsert_property(_room("b1-102", rent=5000, title="ユニオンマンスリーB1 102")),
        "b_901": repo.upsert_property(
            _room(
                "b1-901",
                address=ADDR_B,
                lat=35.67,
                lng=139.71,
                rent=4000,
                title="ユニオンマンスリーB2 901",
                features=[PropertyFeature(feature_name="宅配ボックス", category="delivery_box")],
            )
        ),
    }


def _bulk(client, query: str = "") -> dict:
    res = client.get(f"/api/buildings/geojson{query}")
    assert res.status_code == 200
    return res.json()


def _stream_msgs(client, query: str = "") -> list[dict]:
    """ストリームを NDJSON 行ごとに読んで dict のリストで返す."""
    with client.stream("GET", f"/api/buildings/geojson/stream{query}") as r:
        assert r.status_code == 200
        return [json.loads(line) for line in r.iter_lines() if line]


def test_bulk_groups_rooms_into_building_features(client, seeded):
    """同一住所の 2 部屋 + 別住所 1 部屋 → 2 建物 Feature (units 2/1)."""
    body = _bulk(client)
    assert body["type"] == "FeatureCollection"
    feats = body["features"]
    assert len(feats) == 2

    by_name = {f["properties"]["name"]: f for f in feats}
    assert set(by_name) == {"ユニオンマンスリーB1", "ユニオンマンスリーB2"}

    a = by_name["ユニオンマンスリーB1"]
    props = a["properties"]
    assert props["kind"] == "building"
    assert props["address"] == ADDR_A
    # 建物代表値 (§7): 最安 5000 / 最高 6000・代表座標は geometry 側
    assert props["min_daily_rent"] == 5000
    assert props["max_daily_rent"] == 6000
    assert props["units_count"] == 2
    assert a["geometry"] == {"type": "Point", "coordinates": [139.70, 35.66]}
    assert "lat" not in props and "lng" not in props
    # units は 2 部屋 (部屋単位 payload をそのまま搭載)
    assert sorted(u["external_id"] for u in props["units"]) == ["b1-101", "b1-102"]
    unit_101 = next(u for u in props["units"] if u["external_id"] == "b1-101")
    assert unit_101["min_daily_rent"] == 6000
    assert unit_101["rent_plans"][0]["rent_current_yen"] == 6000
    # 建物レベル feature_categories は sub='building' 語彙の導出
    assert "elevator" in props["feature_categories"]

    b = by_name["ユニオンマンスリーB2"]
    assert len(b["properties"]["units"]) == 1
    assert b["properties"]["units"][0]["external_id"] == "b1-901"


def test_stream_line_contract(client, seeded):
    """meta → feature×N → end の行契約。total / count / feature 行の units."""
    msgs = _stream_msgs(client)
    assert msgs[0]["type"] == "meta"
    # meta.total の単位は建物数 (部屋数 3 ではない)
    assert msgs[0]["total"] == 2
    assert msgs[-1] == {"type": "end", "count": 2}
    feature_msgs = msgs[1:-1]
    assert len(feature_msgs) == 2
    assert all(m["type"] == "feature" for m in feature_msgs)
    feats = [m["feature"] for m in feature_msgs]
    assert all(f["type"] == "Feature" for f in feats)
    a = next(f for f in feats if f["properties"]["name"] == "ユニオンマンスリーB1")
    assert a["properties"]["kind"] == "building"
    assert len(a["properties"]["units"]) == 2

    # limit は建物数に効く: meta は条件一致建物数・end.count は出力建物数
    msgs_lim = _stream_msgs(client, "?limit=1")
    assert msgs_lim[0] == {"type": "meta", "total": 2}
    assert sum(1 for m in msgs_lim if m["type"] == "feature") == 1
    assert msgs_lim[-1] == {"type": "end", "count": 1}


def test_stream_parity_with_bulk(client, seeded):
    """ストリームの feature 行が一括 /api/buildings/geojson と完全一致する."""
    msgs = _stream_msgs(client)
    stream_feats = [m["feature"] for m in msgs if m["type"] == "feature"]
    bulk = _bulk(client)
    assert bulk["features"] == stream_feats


def test_room_geojson_endpoint_removed(client, seeded):
    """B2-ε: 旧部屋単位 /api/geojson は廃止(404)。建物 EP が後継。"""
    res = client.get("/api/geojson")
    assert res.status_code == 404
    assert client.get("/map.geojson").status_code == 404
    assert client.get("/api/geojson/stream").status_code == 404


def test_required_features_filters_buildings(client, seeded):
    """required_features は「条件を満たす部屋を持つ建物」単位で絞る (CSV 文字列)."""
    # elevator は建物 A の 101 のみだが建物単位でヒット。units は全部屋のまま
    res = _bulk(client, "?required_features=elevator")
    assert [f["properties"]["name"] for f in res["features"]] == ["ユニオンマンスリーB1"]
    assert sorted(
        u["external_id"] for u in res["features"][0]["properties"]["units"]
    ) == ["b1-101", "b1-102"]

    # delivery_box は建物 B の 901 のみ
    res_b = _bulk(client, "?required_features=delivery_box")
    assert [f["properties"]["name"] for f in res_b["features"]] == ["ユニオンマンスリーB2"]

    # 誰も満たさない条件は 0 建物
    res_none = _bulk(client, "?required_features=auto_lock")
    assert res_none["features"] == []

    # ストリームの meta.total も建物数で絞られる
    msgs = _stream_msgs(client, "?required_features=elevator")
    assert msgs[0] == {"type": "meta", "total": 1}
    assert msgs[-1] == {"type": "end", "count": 1}


def test_units_carry_floor_and_orientation(client):
    """units に所在階・向きの整数列 (SSOT) が載る.

    docs/fe-floor-orientation-redesign-plan.md §4.1: FE の部屋行 (所在階/方角) は
    この 3 列を消費する。表示用の文字列化 (「5階」「南東」) は消費側 (FE) の責務で、
    API は生値のみを配信する。
    """
    repo = Repository()
    repo.upsert_property(
        _room("f-301", rent=5000, floor_number=3, floor_number_max=3, orientation_deg=135)
    )
    repo.upsert_property(
        _room("f-302", address=ADDR_B, lat=35.67, lng=139.71, rent=4000,
              floor_number=1, floor_number_max=2, orientation_deg=None)
    )
    body = _bulk(client)
    units = {
        u["external_id"]: u
        for f in body["features"]
        for u in f["properties"]["units"]
    }
    # 単一階 + 向きあり (unionmonthly 相当)
    assert units["f-301"]["floor_number"] == 3
    assert units["f-301"]["floor_number_max"] == 3
    assert units["f-301"]["orientation_deg"] == 135
    # 複数階 (「1・2階」) と向き不明 (bratto 相当 = null) もそのまま配信される
    assert (units["f-302"]["floor_number"], units["f-302"]["floor_number_max"]) == (1, 2)
    assert units["f-302"]["orientation_deg"] is None


def test_shortlist_updated_at_propagates(client, seeded):
    """ショートリスト行の updated_at が建物/部屋 properties へ配信される.

    FE 最終編集順ソート (updated_desc) の正本キー。行未登録は null。"""
    repo = Repository()
    repo.update_shortlist(seeded["a_101"], "saved", None)

    body = _bulk(client)
    feats = {f["properties"]["name"]: f for f in body["features"]}
    a_props = feats["ユニオンマンスリーB1"]["properties"]
    a_units = {u["external_id"]: u for u in a_props["units"]}
    # saved 部屋は updated_at を載せる / 未登録部屋・建物行は null
    assert a_units["b1-101"]["shortlist_status"] == "saved"
    assert a_units["b1-101"]["shortlist_updated_at"]
    assert a_units["b1-102"]["shortlist_updated_at"] is None
    assert a_props["shortlist_updated_at"] is None

    # 建物ショートリスト登録で建物側 updated_at が載る
    b_id = feats["ユニオンマンスリーB2"]["properties"]["id"]
    repo.update_building_shortlist(b_id, "saved", None)
    body2 = _bulk(client)
    b_props = next(
        f["properties"] for f in body2["features"] if f["properties"]["name"] == "ユニオンマンスリーB2"
    )
    assert b_props["shortlist_status"] == "saved"
    assert b_props["shortlist_updated_at"]
