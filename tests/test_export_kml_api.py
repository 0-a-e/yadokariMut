#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API tests for /api/export/kml (Google Earth 用 KML エクスポート)."""

import sqlite3
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient


from domain.models import PricePlan, PropertyDraft
from store.repository import Repository
from store.schema import init_schema

KML_NS = "{http://www.opengis.net/kml/2.2}"


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


@pytest.fixture()
def seeded_ids(client):
    """座標あり通常 / 掲載終了 / 座標なしの 3 件をシードして id を返す."""
    repo = Repository()

    def draft(external_id, *, lat=None, lng=None, is_active=True, title=None):
        return PropertyDraft(
            source_site="fakesite",
            external_id=external_id,
            entity_type="room",
            title=title or f"物件 {external_id}",
            detail_url=f"https://example.test/{external_id}/",
            prefecture_name="東京都",
            prefecture_slug="tokyo",
            address="東京都渋谷区神宮前1-2-3",
            lat=lat,
            lng=lng,
            is_active=is_active,
            price_plans=[
                PricePlan(
                    plan_key="short",
                    plan_name="ショット",
                    duration_min_days=30,
                    duration_max_days=89,
                    presentation_unit="per_day",
                    rent_current_yen=5000,
                )
            ],
        )

    return {
        "normal": repo.upsert_property(
            draft("kml-normal", lat=35.66, lng=139.70, title="A&B <ハイツ>")
        ),
        "inactive": repo.upsert_property(
            draft("kml-inactive", lat=35.67, lng=139.71, is_active=False)
        ),
        "nocoords": repo.upsert_property(draft("kml-nocoords")),
    }


def _placemarks(kml_text: str):
    root = ET.fromstring(kml_text)
    doc = root.find(f"{KML_NS}Document")
    return doc.findall(f"{KML_NS}Placemark")


def test_export_kml_basic(client, seeded_ids):
    res = client.post(
        "/api/export/kml",
        json={"ids": [seeded_ids["normal"], seeded_ids["inactive"]]},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/vnd.google-earth.kml+xml")
    assert "attachment" in res.headers["content-disposition"]
    assert '.kml"' in res.headers["content-disposition"]

    # XML としてパースできる
    placemarks = _placemarks(res.text)
    assert len(placemarks) == 2

    first = placemarks[0]
    # リクエスト順が維持される
    assert first.find(f"{KML_NS}name").text == "5,000円 | A&B <ハイツ>"
    # 座標は lng,lat 順
    coords = first.find(f"{KML_NS}Point/{KML_NS}coordinates")
    assert coords.text == "139.7,35.66,0"
    # description は CDATA 内 HTML でタイトル等を含む
    desc = first.find(f"{KML_NS}description").text
    assert "<h3>A&amp;B &lt;ハイツ&gt;</h3>" in desc
    assert "https://example.test/kml-normal/" in desc
    # ExtendedData に機械可読属性
    ext = {
        d.get("name"): d.find(f"{KML_NS}value").text
        for d in first.findall(f"{KML_NS}ExtendedData/{KML_NS}Data")
    }
    assert ext["id"] == str(seeded_ids["normal"])
    assert ext["source_site"] == "fakesite"
    assert ext["is_active"] == "True"


def test_export_kml_style_by_status(client, seeded_ids):
    from store import api_queries

    api_queries.update_shortlist(seeded_ids["normal"], "saved")
    res = client.post(
        "/api/export/kml",
        json={"ids": [seeded_ids["normal"], seeded_ids["inactive"]]},
    )
    assert res.status_code == 200
    placemarks = _placemarks(res.text)
    styles = [pm.find(f"{KML_NS}styleUrl").text for pm in placemarks]
    assert styles == ["#stSaved", "#stInactive"]


def test_export_kml_skips_nocoords_and_keeps_order(client, seeded_ids):
    res = client.post(
        "/api/export/kml",
        json={"ids": [seeded_ids["nocoords"], seeded_ids["inactive"], seeded_ids["normal"]]},
    )
    assert res.status_code == 200
    placemarks = _placemarks(res.text)
    assert len(placemarks) == 2
    names = [pm.find(f"{KML_NS}name").text for pm in placemarks]
    assert names[0].endswith("kml-inactive")
    assert names[1] == "5,000円 | A&B <ハイツ>"


def test_export_kml_inactive_included_even_without_shortlist(client, seeded_ids):
    """is_active=False でも指定 id なら出力される (可視性フィルタを適用しない)."""
    from store import api_queries

    rows = api_queries.get_properties_by_ids([seeded_ids["inactive"]])
    assert len(rows) == 1
    assert rows[0]["is_active"] is False


def test_export_kml_empty_ids_400(client):
    res = client.post("/api/export/kml", json={"ids": []})
    assert res.status_code == 400


def test_export_kml_unknown_ids_404(client):
    res = client.post("/api/export/kml", json={"ids": [999999, 999998]})
    assert res.status_code == 404


def test_export_kml_mixed_unknown_and_known(client, seeded_ids):
    res = client.post(
        "/api/export/kml",
        json={"ids": [999999, seeded_ids["normal"], 999998]},
    )
    assert res.status_code == 200
    placemarks = _placemarks(res.text)
    assert len(placemarks) == 1


def test_export_kml_too_many_ids_400(client):
    res = client.post("/api/export/kml", json={"ids": list(range(1, 20002))})
    assert res.status_code == 400


def test_get_properties_by_ids_dedupes_and_preserves_order(client, seeded_ids):
    from store import api_queries

    rows = api_queries.get_properties_by_ids(
        [seeded_ids["inactive"], seeded_ids["normal"], seeded_ids["inactive"]]
    )
    assert [r["id"] for r in rows] == [seeded_ids["inactive"], seeded_ids["normal"]]


def test_export_kml_file_wrapper_for_mcp(client, seeded_ids, tmp_path):
    """MCP/CLI 用ラッパ: ファイル書き出しと KML 生成の共通化の回帰."""
    from store import api_queries

    out = tmp_path / "map.kml"
    res = api_queries.export_kml({"limit": 10}, str(out))
    assert res["status"] == "success"
    # search_properties の可視性句により inactive(未shortlist)は除外され、
    # 座標あり通常 1 件のみ Placemark 化される
    assert res["placemark_count"] == 1
    ET.fromstring(out.read_text(encoding="utf-8"))
