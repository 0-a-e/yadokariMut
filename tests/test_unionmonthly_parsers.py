#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Union Monthly list/detail parser tests (fixture + synthetic list)."""

import os
import tempfile
import unittest
from pathlib import Path


import sources  # noqa: F401
from domain.pricing import MONTH_DAYS, calculate_stay_total, resolve_plans_effective
from domain.pricing import plan_rent_per_day
from ingest.pipeline import IngestPipeline
from sources.registry import SourceRegistry
from sources.unionmonthly.detail_parser import parse_detail_html
from sources.unionmonthly.list_parser import extract_total_count, parse_list_html
from store.repository import Repository
from helpers import fetch_child_rows, fetch_property_row

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "union-monthly"
# glob 順に依存しないよう明示指定（新フィクスチャ追加時も既存テストが不変）
DETAIL_FIXTURE = FIXTURE_DIR / "unionmonthly_detail_fixture.html"
DETAIL_FIXTURE_5TABS = FIXTURE_DIR / "unionmonthly_detail_5tabs_fixture.html"

SYNTHETIC_LIST = """
<html><body>
<p class="now">2,897 件</p>
<div class="list_item" data-troom_id="6575">
  <h2 class="gArticle_name">ユニオンマンスリー渋谷カディナ１ 903</h2>
  <div class="gArticle_image"><img data-original-src="/img/a.jpg" src="/img/a.jpg"></div>
  <p class="gArticle_price"><b>336,000</b>円</p>
  <ul class="gArticle_infoList">
    <li><i class="icon-marker"></i>東京都 渋谷区 宇田川町</li>
    <li>JR山手線　渋谷駅　徒歩8分</li>
  </ul>
  <a class="u-btn01" href="/tokyo/6575/">詳細</a>
</div>
<div class="list_item" data-troom_id="1500">
  <h2 class="gArticle_name">テスト物件</h2>
  <p class="gArticle_price"><b>100,000</b></p>
  <a class="u-btn01" href="/tokyo/1500/">詳細</a>
</div>
</body></html>
"""

# 和暦築年を含む最小詳細HTML(旧実装は西暦のみで built_year が欠落していた)
ERA_DETAIL_HTML = """
<html><body>
<section class="entry" data-troom_id="9001">
<h1>和暦テスト物件</h1>
<table class="infoTbl_table">
  <tr><th>住所</th><td>東京都 渋谷区 宇田川町</td></tr>
  <tr><th>築年</th><td>平成15年3月</td></tr>
</table>
</section>
</body></html>
"""


class TestListParser(unittest.TestCase):
    def test_parse_synthetic(self):
        cards = parse_list_html(SYNTHETIC_LIST, prefecture_slug="tokyo", prefecture_name="東京都")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].external_id, "6575")
        self.assertEqual(cards[0].list_price_yen, 336000)
        self.assertIn("渋谷", cards[0].address or "")
        self.assertTrue(cards[0].detail_url.endswith("/tokyo/6575/"))
        self.assertEqual(extract_total_count(SYNTHETIC_LIST), 2897)


@unittest.skipUnless(DETAIL_FIXTURE and DETAIL_FIXTURE.exists(), "union detail fixture missing")
class TestDetailParserFixture(unittest.TestCase):
    def setUp(self):
        self.html = DETAIL_FIXTURE.read_text(encoding="utf-8", errors="replace")

    def test_core_fields(self):
        draft = parse_detail_html(
            self.html,
            detail_url="https://www.unionmonthly.jp/tokyo/6575/",
        )
        self.assertEqual(draft.source_site, "unionmonthly")
        self.assertEqual(draft.external_id, "6575")
        self.assertIn("カディナ", draft.title or "")
        self.assertIn("渋谷区", draft.address or "")
        self.assertEqual(draft.prefecture_name, "東京都")
        self.assertEqual(draft.layout, "1LDK")
        self.assertAlmostEqual(draft.area_m2 or 0, 38.91, places=2)
        self.assertEqual(draft.built_year, 2024)
        self.assertEqual(draft.structure, "鉄筋コンクリート造")
        # 所在階: floors_text に原文・floor_number に整数 (docs/floor-number-ssot-plan.md §3.4)
        # 単一階は floor_number_max が min と同値になる
        self.assertEqual(draft.floors_text, "9階")
        self.assertEqual(draft.floor_number, 9)
        self.assertEqual(draft.floor_number_max, 9)
        self.assertIsNone(draft.building_floors)
        # 向き: 原文+角度+取得経路 (docs/orientation-model-plan.md §6.1)
        self.assertEqual(draft.orientation_text, "南東")
        self.assertEqual(draft.orientation_deg, 135)
        self.assertEqual(draft.orientation_source, "spec_parse")
        self.assertIsNotNone(draft.lat)
        self.assertIsNotNone(draft.lng)
        self.assertTrue(any(a.walk_minutes == 8 for a in draft.accesses))
        # 最寄駅th行の <br> 区切り3路線が全て取れること
        stations = [a.station_name for a in draft.accesses]
        self.assertIn("渋谷駅", stations)
        self.assertIn("神泉駅", stations)
        self.assertIn("明治神宮前〈原宿〉駅", stations)
        self.assertGreaterEqual(len(draft.features), 5)
        self.assertEqual(len(draft.price_plans), 3)

    def test_facility_list_active_only(self):
        """facility_list(「物件のこだわり」)は -active の li のみ採る(設計 §7-4)。

        非 active は未達成のグレーアウト表示であり物件事実ではない。fixture の
        facility_list は 10 語彙中「南向き」のみ非 active。entry_tag(サイト運営
        バッジ・常時表示)は active 概念なしでそのまま採る。
        """
        draft = parse_detail_html(
            self.html,
            detail_url="https://www.unionmonthly.jp/tokyo/6575/",
        )
        names = {f.feature_name for f in draft.features}
        self.assertNotIn("南向き", names)  # fixture で非 active の唯一の語彙
        for expected in (
            "バストイレ別", "2階以上", "独立洗面台", "室内洗濯機", "オートロック",
            "モニター付きインターフォン", "インターネット無料", "エアコン", "エレベーター",
        ):
            self.assertIn(expected, names)
        for expected in (
            "敷金礼金仲介料・更新料 ￥0", "家具家電付き", "水道光熱費不要", "来店不要 WEB申込",
        ):
            self.assertIn(expected, names)

    def test_price_plans_monthly(self):
        draft = parse_detail_html(self.html, detail_url="https://www.unionmonthly.jp/tokyo/6575/")
        by_key = {p.plan_key: p for p in draft.price_plans}
        self.assertIn("short", by_key)
        self.assertIn("middle", by_key)
        self.assertIn("long", by_key)
        long_p = by_key["long"]
        self.assertEqual(long_p.presentation_unit, "per_month")
        self.assertEqual(long_p.rent_original_yen, 384000)
        self.assertEqual(long_p.rent_current_yen, 336000)
        self.assertEqual(long_p.management_yen, 28500)
        self.assertEqual(long_p.cleaning_yen, 0)
        self.assertEqual(long_p.duration_min_days, 210)

    def test_stay_total_from_fixture(self):
        draft = parse_detail_html(self.html, detail_url="https://www.unionmonthly.jp/tokyo/6575/")
        plans = resolve_plans_effective(
            draft.price_plans,
            draft.campaigns,
            on_date="2026-08-01",
        )
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-09-15",  # 46 days → short
            plans=plans,
            campaigns=draft.campaigns,
            use_structured_campaigns=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.plan_key, "short")
        rent_d = 354000 // MONTH_DAYS
        mgmt_d = 28500 // MONTH_DAYS
        self.assertEqual(result.breakdown.rent_daily, rent_d)
        self.assertEqual(result.breakdown.management_daily, mgmt_d)

    def test_point_text_strips_leading_boilerplate(self):
        """スタッフのおすすめコメント: 先頭ボイラープレートのみ除去し以降を保持。

        comment-box は [県市駅のテンプレ 2 行][■路線情報][■周辺情報]
        [■おすすめコメント] 構成。■路線情報は accesses に無い乗換情報、
        ■周辺情報は距離付き POI で DB 未保存のため、いずれも保持する
        (2026-10-09・生 HTML 5,315 件全走査に基づく抽出規則)。
        """
        draft = parse_detail_html(
            self.html,
            detail_url="https://www.unionmonthly.jp/tokyo/6575/",
        )
        pt = draft.point_text
        self.assertIsNotNone(pt)
        self.assertTrue(pt.startswith("■路線情報(最寄駅→主要駅)"))
        self.assertIn("■周辺情報", pt)
        self.assertIn("■おすすめコメント", pt)
        # ボイラープレート(建物名テンプレ行)は含まれない
        self.assertNotIn("ユニオンマンスリー渋谷カディナ１です", pt)


class TestPointTextExtraction(unittest.TestCase):
    """_parse_point_text の抽出規則(マーカー変種・フォールバック)。

    実データの先頭マーカーは ■系/＜＞系の両方(■路線情報 4,789 /
    ＜路線情報(最寄駅→主要駅)＞ 442 / ＜物件の特徴＞ 21 / ＜○○駅おすすめコメント＞ 等)。
    """

    def _parse(self, body_html: str):
        from bs4 import BeautifulSoup

        from sources.unionmonthly.detail_parser import _parse_point_text

        html = f"<html><body>{body_html}</body></html>"
        return _parse_point_text(BeautifulSoup(html, "html.parser"))

    def test_standard_block_markers(self):
        pt = self._parse(
            '<section class="comment"><h2>スタッフのおすすめコメント</h2>'
            '<div class="comment-box">東京都渋谷区のテンプレ行です<br>ユニオンマンスリー○○です<br>'
            "■路線情報(最寄駅→主要駅)<br>・渋谷駅→新宿駅（約7分/乗り換えなし）<br>"
            "■周辺情報<br>・ローソン(約130ｍ)<br>"
            "■おすすめコメント<br>駅近で利便性抜群です。</div></section>"
        )
        self.assertEqual(
            pt,
            "■路線情報(最寄駅→主要駅)\n・渋谷駅→新宿駅（約7分/乗り換えなし）\n"
            "■周辺情報\n・ローソン(約130ｍ)\n■おすすめコメント\n駅近で利便性抜群です。",
        )

    def test_bracket_marker_variant(self):
        pt = self._parse(
            '<section class="comment"><div class="comment-box">'
            "建物テンプレです<br>＜大宮駅おすすめコメント＞<br>自由文です。</div></section>"
        )
        self.assertEqual(pt, "＜大宮駅おすすめコメント＞\n自由文です。")

    def test_marker_first_line_kept_whole(self):
        pt = self._parse(
            '<section class="comment"><div class="comment-box">'
            "＜物件の特徴＞<br>内容です。</div></section>"
        )
        self.assertEqual(pt, "＜物件の特徴＞\n内容です。")

    def test_no_marker_falls_back_to_full_text(self):
        pt = self._parse(
            '<section class="comment"><div class="comment-box">'
            "自由文のみの変種です。</div></section>"
        )
        self.assertEqual(pt, "自由文のみの変種です。")

    def test_no_section_returns_none(self):
        self.assertIsNone(self._parse(""))

    def test_empty_box_returns_none(self):
        pt = self._parse(
            '<section class="comment"><div class="comment-box">   </div></section>'
        )
        self.assertIsNone(pt)


@unittest.skipUnless(DETAIL_FIXTURE_5TABS.exists(), "union 5-tabs fixture missing")
class TestDetailParser5Tabs(unittest.TestCase):
    """スーパーショート/セミショート（円/日）を含む5タブページの検証。"""

    @classmethod
    def setUpClass(cls):
        cls.html = DETAIL_FIXTURE_5TABS.read_text(encoding="utf-8", errors="replace")
        cls.draft = parse_detail_html(cls.html, detail_url="https://www.unionmonthly.jp/kanagawa/room/9999/")

    def test_plan_keys_units_bands(self):
        plans = {p.plan_key: p for p in self.draft.price_plans}
        self.assertEqual(
            set(plans), {"s_short", "semi_short", "short", "middle", "long"}
        )
        expected = {
            "s_short": ("per_day", 7, 14),
            "semi_short": ("per_day", 15, 29),
            "short": ("per_month", 30, 89),
            "middle": ("per_month", 90, 209),
            "long": ("per_month", 210, 729),
        }
        for key, (unit, dmin, dmax) in expected.items():
            self.assertEqual(plans[key].presentation_unit, unit, key)
            self.assertEqual(plans[key].duration_min_days, dmin, key)
            self.assertEqual(plans[key].duration_max_days, dmax, key)

    def test_plan_amounts(self):
        plans = {p.plan_key: p for p in self.draft.price_plans}
        # 生HTML（2026-07-23取得・清掃費半額）の表示値
        self.assertEqual(plans["s_short"].rent_original_yen, 6710)
        self.assertEqual(plans["s_short"].rent_current_yen, 4180)
        self.assertEqual(plans["s_short"].management_yen, 704)
        self.assertEqual(plans["s_short"].cleaning_yen, 12100)
        self.assertEqual(plans["semi_short"].rent_original_yen, 5390)
        self.assertEqual(plans["semi_short"].rent_current_yen, 3520)
        self.assertEqual(plans["long"].rent_original_yen, 87000)
        self.assertEqual(plans["long"].rent_current_yen, 57000)
        self.assertEqual(plans["long"].management_yen, 19200)
        self.assertEqual(plans["long"].cleaning_yen, 18150)

    def test_campaigns_exclude_site_wide_banner(self):
        titles = [c.title for c in self.draft.campaigns]
        self.assertNotIn("嬉しい3大特典キャンペーン", titles)
        # キャンペーン料金が存在するためマーカーは1件立つ
        self.assertEqual(len(self.draft.campaigns), 1)
        self.assertEqual(self.draft.campaigns[0].title, "キャンペーン料金")

    def test_per_day_plan_resolves_daily_rent(self):
        resolved = resolve_plans_effective(self.draft.price_plans)
        s_short = next(p for p in resolved if p.plan_key == "s_short")
        self.assertEqual(plan_rent_per_day(s_short), 4180)


class TestBuiltYearJapaneseEra(unittest.TestCase):
    """和暦(昭和/平成/令和)表記の築年でも built_year が欠落しないこと。"""

    def test_heisei_built_year_via_detail_html(self):
        draft = parse_detail_html(
            ERA_DETAIL_HTML,
            detail_url="https://www.unionmonthly.jp/tokyo/9001/",
        )
        self.assertEqual(draft.external_id, "9001")
        self.assertEqual(draft.built_year, 2003)
        self.assertEqual(draft.built_month, 3)
        self.assertEqual(draft.construction_year_text, "平成15年3月")

    def test_parse_built_variants(self):
        from sources.unionmonthly.detail_parser import _parse_built

        self.assertEqual(_parse_built("昭和59年7月"), (1984, 7, "昭和59年7月"))
        self.assertEqual(_parse_built("令和元年5月"), (2019, 5, "令和元年5月"))
        self.assertEqual(_parse_built("令和6年11月築"), (2024, 11, "令和6年11月築"))
        self.assertEqual(_parse_built("2024年11月"), (2024, 11, "2024年11月"))
        self.assertEqual(_parse_built("2024年"), (2024, None, "2024年"))
        self.assertEqual(_parse_built("不明"), (None, None, "不明"))
        self.assertEqual(_parse_built(""), (None, None, None))
        self.assertEqual(_parse_built(None), (None, None, None))


class TestMinStayDays(unittest.TestCase):
    """最低契約日数表記 → min_stay_days への換算。

    月表記は domain.pricing.MONTH_DAYS (正本) で日数換算する。
    """

    def _draft_with_min_stay_text(self, text: str):
        html = f"""
<html><body>
<section class="entry" data-troom_id="9100">
<h1>最低契約テスト物件</h1>
<p>{text}</p>
</section>
</body></html>
"""
        return parse_detail_html(html, detail_url="https://www.unionmonthly.jp/tokyo/9100/")

    def test_min_stay_two_months_is_sixty_days(self):
        draft = self._draft_with_min_stay_text("最低契約日数2ヶ月からご入居いただけます")
        self.assertEqual(draft.min_stay_days, 2 * MONTH_DAYS)
        self.assertEqual(draft.min_stay_days, 60)

    def test_min_stay_days_unit_kept_as_is(self):
        draft = self._draft_with_min_stay_text("最低契約日数45日からご入居いただけます")
        self.assertEqual(draft.min_stay_days, 45)


class TestRegistryAndPipelineFixture(unittest.TestCase):
    def test_registry(self):
        self.assertIsNotNone(SourceRegistry.get("unionmonthly"))
        adapter = SourceRegistry.create("unionmonthly", {"delay_seconds": 0})
        self.assertEqual(adapter.source_id, "unionmonthly")
        targets = adapter.discover_list_targets()
        self.assertGreaterEqual(len(targets), 1)

    @unittest.skipUnless(DETAIL_FIXTURE and DETAIL_FIXTURE.exists(), "union detail fixture missing")
    def test_pipeline_fixture_upsert(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            repo = Repository()
            adapter = SourceRegistry.create("unionmonthly", {"delay_seconds": 0})
            pipeline = IngestPipeline(adapter, repo, save_raw=False)
            html = DETAIL_FIXTURE.read_text(encoding="utf-8", errors="replace")
            pid = pipeline.ingest_detail_html(
                html,
                detail_url="https://www.unionmonthly.jp/tokyo/6575/",
                external_id="6575",
                prefecture_slug="tokyo",
                prefecture_name="東京都",
            )
            self.assertEqual(fetch_property_row(repo, pid)["source_site"], "unionmonthly")
            self.assertEqual(fetch_property_row(repo, pid)["external_id"], "6575")
            self.assertEqual(len(fetch_child_rows(repo, pid, "price_plans")), 3)
            self.assertEqual(
                fetch_property_row(repo, pid)["catalog_rent_per_day_yen"],
                336000 // MONTH_DAYS,
            )
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
