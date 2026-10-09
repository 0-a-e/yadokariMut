#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_properties の子テーブル一括取得(IN句)が物件ごとに正しく束ねられること."""

from __future__ import annotations

import unittest


from domain.feature_categories import lookup_feature_category  # noqa: E402
from domain.models import (  # noqa: E402
    Campaign,
    PricePlan,
    PropertyAccess,
    PropertyDraft,
    PropertyFeature,
    PropertyImage,
)
from helpers import ScopedDb, make_draft  # noqa: E402
from store import api_queries  # noqa: E402
from store.repository import Repository  # noqa: E402


def _draft(
    eid: str,
    *,
    walk: int = 5,
    features: list[str] | None = None,
    with_children: bool = True,
) -> PropertyDraft:
    draft = make_draft(eid)
    if not with_children:
        return draft
    draft.accesses = [
        PropertyAccess(
            line_name="JR",
            station_name=f"{eid}駅",
            walk_minutes=walk,
            sort_order=0,
        )
    ]
    # sort_order 逆順で投入し、取得側の ORDER BY が効くことを確認する
    draft.images = [
        PropertyImage(
            image_url=f"https://img.test/{eid}-b.jpg",
            image_type="gallery",
            sort_order=1,
        ),
        PropertyImage(
            image_url=f"https://img.test/{eid}-a.jpg",
            image_type="thumbnail",
            sort_order=0,
        ),
    ]
    # 生産器 (parser) と同一の書き込み契約 (決定 4): 辞書既知語は category code、
    # 未知語は NULL。検索 SQL 化 (決定 10) の EXISTS pf.category IN は category 列を
    # 直読するため、required_features 系テストはこの category 付き fixture を前提とする
    draft.features = [
        PropertyFeature(
            feature_name=f,
            category=(
                lookup_feature_category(f).code
                if lookup_feature_category(f) is not None
                else None
            ),
        )
        for f in (features or [])
    ]
    draft.price_plans = [
        PricePlan(
            plan_key="long",
            plan_name="ロング",
            duration_min_days=210,
            duration_max_days=729,
            presentation_unit="per_day",
            rent_current_yen=5000,
        ),
        PricePlan(
            plan_key="short",
            plan_name="ショート",
            duration_min_days=30,
            duration_max_days=89,
            presentation_unit="per_day",
            rent_current_yen=8000,
        ),
    ]
    draft.campaigns = [
        Campaign(
            title=f"{eid}キャンペーン",
            target_plan_key="long",
            discount_unit="yen",
            discount_value=1000,
        )
    ]
    return draft


class SearchBatchingTest(unittest.TestCase):
    def setUp(self):
        self._db = ScopedDb("batch")
        self.addCleanup(self._db.close)
        self.repo = Repository()
        conn = self.repo.connect()
        try:
            conn.execute("DELETE FROM property_shortlists")
            conn.execute("DELETE FROM properties")
            conn.commit()
        finally:
            conn.close()

    def _by_external_id(self, params=None) -> dict[str, dict]:
        rows = api_queries.search_properties(params or {"limit": 50})
        return {r["external_id"]: r for r in rows}

    def test_children_are_grouped_per_property(self):
        """子テーブルをIN一括取得しても、各物件に自分の子行だけが紐づく."""
        for eid in ("p1", "p2", "p3"):
            self.repo.upsert_property(_draft(eid, walk=5))

        by_id = self._by_external_id()
        self.assertEqual(set(by_id), {"p1", "p2", "p3"})
        for eid in ("p1", "p2", "p3"):
            row = by_id[eid]
            # 画像は sort_order 昇順、かつ他物件のURLが混ざらない
            self.assertEqual(
                [img["image_url"] for img in row["images"]],
                [f"https://img.test/{eid}-a.jpg", f"https://img.test/{eid}-b.jpg"],
            )
            self.assertEqual(
                {k for img in row["images"] for k in img},
                # media_id/dhash/has_thumb は rustfs メディア結合列(未取得行は
                # media_id=None/dhash=None/has_thumb=False・docs/media-storage-rustfs-plan.md §2.8)
                {"image_url", "image_type", "sort_order", "media_id", "dhash", "has_thumb"},
            )
            # アクセス・料金プランも自物件のみ
            self.assertIn(f"{eid}駅", row["access_summary"][0])
            self.assertEqual(
                [p["plan_key"] for p in row["rent_plans"]], ["short", "long"]
            )
            # plan_label は辞書解決ラベル (レンジ無し) で配信される (設計 §3.6)
            self.assertEqual(
                [p["plan_label"] for p in row["rent_plans"]], ["ショート", "ロング"]
            )
            self.assertEqual(len(row["campaigns"]), 1)
            self.assertEqual(row["campaigns"][0]["title"], f"{eid}キャンペーン")
            self.assertEqual(row["campaigns"][0]["target_plan_code"], "long")
            self.assertEqual(row["campaigns"][0]["target_plan_label"], "ロング")

    def test_required_features_filter(self):
        """required_features は SQL 前段 (EXISTS category IN) で物件単位に絞られる."""
        self.repo.upsert_property(_draft("p1", features=["オートロック", "宅配ボックス"]))
        self.repo.upsert_property(_draft("p2", features=["オートロック"]))
        self.repo.upsert_property(_draft("p3", features=[]))

        by_id = self._by_external_id(
            {"limit": 50, "required_features": ["オートロック", "宅配ボックス"]}
        )
        self.assertEqual(set(by_id), {"p1"})

    def test_required_features_unknown_raw_falls_back_to_exact_name(self):
        """生名 fallback 要件 (辞書外生値) は同一 EXISTS 内の feature_name = ? で判定される.

        決定 10: code 要件 (category IN) と生名 fallback (feature_name = 実値) は
        いずれも SQL 前段で表現され、post filter への切り替えは存在しない。
        辞書既知語と同名でも code へ解決されない生値 (ここでは架空語) の完全一致のみ
        マッチすることを、category=NULL 行で確認する。
        """
        self.repo.upsert_property(_draft("p1", features=["オートロック", "謎設備XYZ"]))
        self.repo.upsert_property(_draft("p2", features=["オートロック"]))

        # 辞書外生値は寛容受入で code 化されないため fallback (実値完全一致) になる
        self.assertIsNone(lookup_feature_category("謎設備XYZ"))
        by_id = self._by_external_id({"limit": 50, "required_features": ["謎設備XYZ"]})
        self.assertEqual(set(by_id), {"p1"})

    def test_required_features_code_and_fallback_are_anded(self):
        """code 要件と生名 fallback 要件の混在も AND で結合される."""
        self.repo.upsert_property(_draft("p1", features=["エアコン", "謎設備XYZ"]))
        self.repo.upsert_property(_draft("p2", features=["エアコン"]))
        self.repo.upsert_property(_draft("p3", features=["謎設備XYZ"]))

        by_id = self._by_external_id(
            {"limit": 50, "required_features": ["aircon", "謎設備XYZ"]}
        )
        self.assertEqual(set(by_id), {"p1"})

    def test_required_features_csv_normalized_in_queries_layer(self):
        """CSV 正規化 (strip + 空要素除去) の正本は queries 層 (H2一本化).

        router / cli の前分割は廃止済み。スペース入り CSV (' オートロック ,
        宅配ボックス ') も 2 要素として解釈され、旧 cli.py の strip 無し
        split による一致失敗 (スペース込み生値 fallback → 0 件) が起きない。
        """
        self.repo.upsert_property(_draft("p1", features=["オートロック", "宅配ボックス"]))
        self.repo.upsert_property(_draft("p2", features=["オートロック"]))

        # スペース入り CSV → strip されて 2 要素 (AND) として解釈される
        by_id = self._by_external_id(
            {"limit": 50, "required_features": " オートロック , 宅配ボックス "}
        )
        self.assertEqual(set(by_id), {"p1"})

        # 空要素 (連続カンマ) は除去され、要件数は 2 のまま
        by_id = self._by_external_id(
            {"limit": 50, "required_features": "オートロック,,宅配ボックス,"}
        )
        self.assertEqual(set(by_id), {"p1"})

    def test_max_walk_filter(self):
        """max_walk は SQL の min_walk_minutes で従来どおり判定される."""
        self.repo.upsert_property(_draft("p1", walk=5))
        self.repo.upsert_property(_draft("p2", walk=20))

        by_id = self._by_external_id({"limit": 50, "max_walk_minutes": 10})
        self.assertEqual(set(by_id), {"p1"})

    def test_large_result_set_spans_in_chunks(self):
        """IN句のチャンク境界(900件)をまたぐ件数でも取りこぼさない."""
        total = 920
        for i in range(total):
            self.repo.upsert_property(_draft(f"bulk{i}", with_children=False))
        by_id = self._by_external_id({"limit": total})
        self.assertEqual(len(by_id), total)


if __name__ == "__main__":
    unittest.main()
