#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_properties の子テーブル一括取得(IN句)が物件ごとに正しく束ねられること."""

from __future__ import annotations

import os
import tempfile
import unittest


_TMPDIR = tempfile.mkdtemp(prefix="yadm-batch-")
os.environ["YADOKARIMUT_V2_DB_PATH"] = os.path.join(_TMPDIR, "test_v2.db")


from domain.models import (  # noqa: E402
    Campaign,
    PricePlan,
    PropertyAccess,
    PropertyDraft,
    PropertyFeature,
    PropertyImage,
)
from store import api_queries  # noqa: E402
from store.repository import Repository  # noqa: E402


def _draft(
    eid: str,
    *,
    walk: int = 5,
    features: list[str] | None = None,
    with_children: bool = True,
) -> PropertyDraft:
    draft = PropertyDraft(
        source_site="fakesite",
        external_id=eid,
        entity_type="room",
        title=f"物件 {eid}",
        detail_url=f"https://example.test/{eid}/",
        prefecture_name="東京都",
        prefecture_slug="tokyo",
        is_active=True,
    )
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
    draft.features = [
        PropertyFeature(feature_name=f, feature_category="building")
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
        self.repo = Repository()
        self.repo.init_db()
        conn = self.repo.connect()
        try:
            conn.execute("DELETE FROM shortlists")
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
                {"image_url", "image_type", "sort_order"},
            )
            # アクセス・料金プランも自物件のみ
            self.assertIn(f"{eid}駅", row["access_summary"][0])
            self.assertEqual(
                [p["plan_key"] for p in row["rent_plans"]], ["short", "long"]
            )
            self.assertEqual(len(row["campaigns"]), 1)
            self.assertEqual(row["campaigns"][0]["title"], f"{eid}キャンペーン")
            self.assertEqual(row["campaigns"][0]["target_plan_code"], "long")

    def test_required_features_filter(self):
        """required_features は一括取得した特徴でも物件単位で判定される."""
        self.repo.upsert_property(_draft("p1", features=["オートロック", "宅配ボックス"]))
        self.repo.upsert_property(_draft("p2", features=["オートロック"]))
        self.repo.upsert_property(_draft("p3", features=[]))

        by_id = self._by_external_id(
            {"limit": 50, "required_features": ["オートロック", "宅配ボックス"]}
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
