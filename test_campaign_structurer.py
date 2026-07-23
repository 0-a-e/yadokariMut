#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from campaign_structurer import (
    structure_mechanically,
    extract_cam_js_objects,
    structure_from_cam_js,
    structure_campaign,
    match_cam_js,
)
from parser import parse_dates_from_text


class TestCampaignStructurer(unittest.TestCase):
    def test_hayawari(self):
        s = structure_mechanically(
            "早割",
            "賃料1日1000円割引キャンペーン！【最大120,000円割引】",
            "賃料1日1000円割引キャンペーン！ 「最大120日間適用！」",
        )
        self.assertEqual(s["target_plan_code"], "all")
        self.assertEqual(s["discount_unit"], "yen")
        self.assertEqual(s["discount_value"], 1000)
        self.assertEqual(s["discount_max_yen"], 120000)
        self.assertEqual(s["period_max_days"], 120)
        self.assertEqual(s["parse_ok"], 1)

    def test_special_percent(self):
        s = structure_mechanically(
            "特別割引",
            "5月限定！新緑キャンペーン【最大14日間適用】50%OFF!",
            "5月限定！新緑キャンペーン",
        )
        self.assertEqual(s["target_plan_code"], "s_short")
        self.assertEqual(s["discount_unit"], "percent")
        self.assertEqual(s["discount_value"], 50)
        self.assertEqual(s["period_max_days"], 14)
        self.assertEqual(s["parse_ok"], 1)

    def test_middle_package(self):
        s = structure_mechanically(
            "ミドル割",
            "✨ミドルプラン（3～6か月間）のお客様限定キャンペーン！✨",
            "ミドルプランの方限定！最大12万円+清掃費27,500円の半額＝133,750円オトクに♪（他キャンペーンとの併用可！）",
        )
        self.assertEqual(s["target_plan_code"], "middle")
        self.assertEqual(s["discount_unit"], "package")
        self.assertEqual(s["package_rent_benefit_yen"], 120000)
        self.assertEqual(s["package_cleaning_benefit_yen"], 13750)
        self.assertEqual(s["package_total_benefit_yen"], 133750)
        self.assertEqual(s["parse_ok"], 1)

    def test_long_package(self):
        s = structure_mechanically(
            "ロング割",
            "🌟ロングプラン（6か月間～）はもっとオトクなキャンペーン！🌟",
            "ロングプランの方限定！12万円+清掃費38,500円+契約事務手数料5,500円＝164,000円もオトクに♪（他キャンペーンとの併用可！）",
        )
        self.assertEqual(s["target_plan_code"], "long")
        self.assertEqual(s["package_fee_benefit_yen"], 5500)
        self.assertEqual(s["package_total_benefit_yen"], 164000)
        self.assertEqual(s["parse_ok"], 1)

    def test_500yen(self):
        s = structure_mechanically(
            "500円割",
            "賃料1日500円割引　【最大45000円割引】",
            "7日間以上のご利用で1日賃料500円割引！ 【最大90日間適用】 ※90日以上ご滞在のご契約の際、最大45000円割引",
        )
        self.assertEqual(s["discount_unit"], "yen")
        self.assertEqual(s["discount_value"], 500)
        self.assertEqual(s["stay_min_days"], 7)
        self.assertEqual(s["period_max_days"], 90)
        self.assertEqual(s["discount_max_yen"], 45000)
        self.assertEqual(s["parse_ok"], 1)

    def test_pokkiri(self):
        s = structure_mechanically(
            "ポッキリ割",
            "【ポッキリ割引】1ヶ月以上の利用で1ヶ月10万円ポッキリでご利用可能！",
            "30日以上のご利用で一ヶ月10万円でご利用可能！",
        )
        self.assertEqual(s["target_plan_code"], "short")
        self.assertEqual(s["discount_unit"], "pokkiri")
        self.assertEqual(s["discount_value"], 100000)
        self.assertEqual(s["parse_ok"], 1)

    def test_cam_js_extract_and_merge(self):
        html = '''
        var cam_1 = {cam_label: "特別割引",cam_discount: 50,cam_discount_unit: "percent",cam_discount_max: 0,cam_period_max: 14,cam_conditions_period: 7,cam_conditions_period_max: 29,};
        var cam_2 = {cam_label: "早割",cam_discount: 1000,cam_discount_unit: "yen",cam_discount_max: 120000,cam_period_max: 120,cam_conditions_period: 21,cam_conditions_period_max: 9999,};
        '''
        cams = extract_cam_js_objects(html)
        self.assertEqual(len(cams), 2)
        self.assertEqual(cams[0]["label"], "特別割引")
        self.assertEqual(cams[1]["discount"], 1000)

        matched = match_cam_js("早割", "賃料1日1000円", cams)
        self.assertIsNotNone(matched)
        js = structure_from_cam_js(matched, "早割")
        self.assertEqual(js["discount_unit"], "yen")
        self.assertEqual(js["stay_min_days"], 21)
        self.assertIsNone(js["stay_max_days"])  # 9999 → unbounded

        full = structure_campaign(
            campaign_type="早割",
            title="賃料1日1000円割引",
            content="最大120日間適用",
            cam_objects=cams,
        )
        self.assertEqual(full["target_plan_code"], "all")
        self.assertIn(full["structure_source"], ("cam_js+mechanical", "cam_js", "mechanical"))
        self.assertEqual(full["discount_value"], 1000)

    def test_dates_year_carry(self):
        s, e = parse_dates_from_text("2026年5月1日から5月31日までの間にご契約いただいた方対象！")
        self.assertEqual(s, "2026-05-01")
        self.assertEqual(e, "2026-05-31")

    def test_dates_month_only(self):
        s, e = parse_dates_from_text("2026年5月", default_year=2026)
        self.assertEqual(s, "2026-05-01")
        self.assertEqual(e, "2026-05-31")

    def test_contract_within(self):
        s = structure_mechanically(
            "早割",
            "title",
            "content",
            condition_text="上記期間にご入居開始で本日より3日以内にご契約いただいたお客様対象！",
        )
        self.assertEqual(s["contract_within_days"], 3)

    def test_hayawari_ignores_garbage_percent(self):
        s = structure_mechanically(
            "早割",
            "賃料1日1000円割引キャンペーン！【最大120,000円割引】1000%OFF!",
            "賃料1日1000円割引キャンペーン！ 「最大120日間適用！」",
        )
        self.assertEqual(s["discount_unit"], "yen")
        self.assertEqual(s["discount_value"], 1000)
        self.assertEqual(s["parse_ok"], 1)

    def test_special_lump_off(self):
        s = structure_mechanically(
            "特別割引",
            "7月限定！今だけ賃料から1万円OFF！お得に始める特別キャンペーン",
            "7月限定！今だけ賃料から1万円OFF！お得に始める特別キャンペーン",
        )
        self.assertEqual(s["discount_unit"], "yen")
        self.assertEqual(s["discount_value"], 10000)
        self.assertEqual(s["parse_ok"], 1)


if __name__ == "__main__":
    unittest.main()
