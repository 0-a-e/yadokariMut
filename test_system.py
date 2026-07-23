import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure YADOKARIMUT_DB_PATH before importing database module
os.environ["YADOKARIMUT_DB_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_yadokariMut.db")

import unittest
import json
import sqlite3
from database import get_db_connection, init_db, DB_PATH
from parser import parse_japanese_era, parse_money, parse_area, parse_walk_minutes, parse_dates_from_text, parse_list_page, parse_detail_page, normalize_property
from scraper import upsert_normalized_property
from commute_scorer import calculate_property_score
from anomaly_detector import detect_anomalies
from services import db_search_properties, db_get_property_detail, db_compare_properties, db_update_shortlist

class TestMonthlyMansionSystem(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # We will use a test database path
        cls.orig_db_path = DB_PATH
        # Reset DB for fresh test run
        init_db()
        
    @classmethod
    def tearDownClass(cls):
        # Clean up the test database file
        test_db = os.environ.get("YADOKARIMUT_DB_PATH")
        if test_db and os.path.exists(test_db):
            try:
                os.remove(test_db)
            except Exception:
                pass
                
    def test_parser_helpers(self):
        # Test japanese era parsing
        self.assertEqual(parse_japanese_era("昭和59年7月"), (1984, 7))
        self.assertEqual(parse_japanese_era("平成10年5月"), (1998, 5))
        self.assertEqual(parse_japanese_era("令和7年3月"), (2025, 3))
        self.assertEqual(parse_japanese_era("200612"), (2006, 12))
        self.assertEqual(parse_japanese_era("2006年12月"), (2006, 12))
        self.assertEqual(parse_japanese_era("invalid"), (None, None))
        
        # Test money parsing
        self.assertEqual(parse_money("4,900円/日"), 4900)
        self.assertEqual(parse_money("16,500"), 16500)
        self.assertEqual(parse_money(""), None)
        # Period suffix must not be concatenated into the amount
        self.assertEqual(parse_money("(月 75,000円/30日)"), 75000)
        self.assertEqual(parse_money("(週 14,350円/7日)"), 14350)
        self.assertEqual(parse_money("(月 84,000円/30日)"), 84000)
        self.assertEqual(parse_money("-1,080,000円/30日"), -1080000)
        self.assertEqual(parse_money(None), None)

    def test_migrate_rent_totals_from_raw(self):
        """raw_text の期間付き総額から正しい金額を復元できること。"""
        from migrate_rent_totals import extract_totals_from_raw, recover_from_period_suffix

        # 30日プラン（連結バグの典型）
        orig, disc = extract_totals_from_raw(
            "早割キャンペーン\n\n3,500円/日\n➡\n2,500円/日\n\n\n"
            "(月 105,000円/30日)\n➡\n(月 75,000円/30日)"
        )
        self.assertEqual(orig, 105000)
        self.assertEqual(disc, 75000)

        # 7日プラン（143507 のように見えても正しくは 14350）
        orig, disc = extract_totals_from_raw(
            "短期割キャンペーン\n\n4,100円/日\n➡\n2,050円/日\n\n\n"
            "(週 28,700円/7日)\n➡\n(週 14,350円/7日)"
        )
        self.assertEqual(orig, 28700)
        self.assertEqual(disc, 14350)

        self.assertEqual(recover_from_period_suffix(7500030, 2500, 30), 75000)
        self.assertEqual(recover_from_period_suffix(143507, 2050, 7), 14350)
        self.assertEqual(recover_from_period_suffix(75000, 2500, 30), 75000)
        self.assertIsNone(recover_from_period_suffix(99999, 2500, 30))
        
        # Test area parsing
        self.assertEqual(parse_area("19.16㎡"), 19.16)
        self.assertEqual(parse_area("25sqm"), 25.0)
        
        # Test walk minutes parsing
        self.assertEqual(parse_walk_minutes("徒歩 5分"), 5)
        self.assertEqual(parse_walk_minutes("バス 12分"), 12)

        # Test date range/text parsing
        self.assertEqual(parse_dates_from_text("2026年4月26日から2026年5月25日までの間"), ("2026-04-26", "2026-05-25"))
        self.assertEqual(parse_dates_from_text("2026年5月1日から5月31日までの間"), ("2026-05-01", "2026-05-31"))
        self.assertEqual(parse_dates_from_text("5月1日〜5月31日", default_year=2026), ("2026-05-01", "2026-05-31"))
        self.assertEqual(parse_dates_from_text("2026/05/21 ~ 2026/06/20"), ("2026-05-21", "2026-06-20"))
        self.assertEqual(parse_dates_from_text("2026-05-21"), ("2026-05-21", None))
        self.assertEqual(parse_dates_from_text("2026年5月"), ("2026-05-01", "2026-05-31"))
        self.assertEqual(parse_dates_from_text("2026/05"), ("2026-05-01", "2026-05-31"))
        self.assertEqual(parse_dates_from_text(""), (None, None))

    def test_local_html_parsing(self):
        # Optional local HTML fixtures (not shipped; place under fixtures/ if needed)
        repo_root = os.path.dirname(os.path.abspath(__file__))
        list_html_path = os.path.join(repo_root, "fixtures", "tokyo.search_list.pn-3.html")
        detail_html_path = os.path.join(
            repo_root, "fixtures", "BraTTo千駄ヶ谷ドール(渋谷区).html"
        )

        if not os.path.exists(list_html_path) or not os.path.exists(detail_html_path):
            self.skipTest("Optional fixtures not found (fixtures/*.html).")
            
        with open(list_html_path, "r", encoding="utf-8") as f:
            list_html = f.read()
        with open(detail_html_path, "r", encoding="utf-8") as f:
            detail_html = f.read()
            
        # Parse list page
        properties, page_info, has_next, next_url = parse_list_page(list_html)
        self.assertTrue(len(properties) > 0)
        self.assertIsNotNone(page_info)
        
        # Parse detail page
        detail_data = parse_detail_page(detail_html)
        self.assertEqual(detail_data["json_ld"]["name"], "BraTTo千駄ヶ谷ドール")
        self.assertEqual(float(detail_data["json_ld"]["geo"]["latitude"]), 35.677133)
        self.assertEqual(len(detail_data["rent_plans"]), 4)
        self.assertEqual(len(detail_data["campaigns"]), 3)
        
        # Normalize
        target_item = properties[0]
        normalized = normalize_property(target_item, detail_data)
        self.assertEqual(normalized["source_site"], "bratto")
        self.assertEqual(normalized["built_year"], 1984)
        self.assertEqual(normalized["built_month"], 7)
        self.assertEqual(normalized["area_m2"], 19.16)
        self.assertEqual(normalized["prefecture_name"], "東京都")
        self.assertEqual(normalized["prefecture_slug"], "tokyo")
        self.assertTrue(len(normalized["accesses"]) > 0)
        
    def test_prefecture_normalization(self):
        # 1. Test when list_data has prefecture_name and prefecture_slug (scraped list item)
        list_item_osaka = {
            "title": "Test Osaka Bukken",
            "room_id": "12345",
            "address": "大阪府大阪市北区梅田1-1-1",
            "prefecture_name": "大阪府",
            "prefecture_slug": "osaka"
        }
        detail_empty = {"json_ld": {}, "specs": {}, "rent_plans": [], "campaigns": [], "youtube_links": [], "images": []}
        normalized = normalize_property(list_item_osaka, detail_empty)
        self.assertEqual(normalized["prefecture_name"], "大阪府")
        self.assertEqual(normalized["prefecture_slug"], "osaka")

        # 2. Test when JSON-LD is missing, and list_data doesn't have prefecture info, but address starts with prefecture
        list_item_kyoto = {
            "title": "Test Kyoto Bukken",
            "room_id": "12346",
            "address": "京都府京都市下京区",
        }
        normalized = normalize_property(list_item_kyoto, detail_empty)
        self.assertEqual(normalized["prefecture_name"], "京都府")
        self.assertEqual(normalized["prefecture_slug"], "kyoto")

        # 3. Test list-only import where only prefecture_slug is known (fallback name from slug)
        list_item_fukuoka = {
            "title": "Test Fukuoka Bukken",
            "room_id": "12347",
            "prefecture_slug": "fukuoka"
        }
        normalized = normalize_property(list_item_fukuoka, detail_empty)
        self.assertEqual(normalized["prefecture_name"], "福岡県")
        self.assertEqual(normalized["prefecture_slug"], "fukuoka")

        # 4. Fallback to Tokyo if completely unknown
        list_item_unknown = {
            "title": "Test Unknown Bukken",
            "room_id": "12348",
        }
        normalized = normalize_property(list_item_unknown, detail_empty)
        self.assertEqual(normalized["prefecture_name"], "東京都")
        self.assertEqual(normalized["prefecture_slug"], "tokyo")
        
    def test_database_crud_and_scoring(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        
        mock_data = {
            "source_site": "bratto",
            "source_property_id": "test_room_999",
            "title": "Test Apartment Shinjuku",
            "detail_url": "https://www.example.com/shinjuku",
            "address": "東京都新宿区歌舞伎町1-1-1",
            "prefecture_name": "東京都",
            "lat": 35.6938,
            "lng": 139.7035,
            "geocode_source": "mock",
            "geocode_confidence": 1.0,
            "layout": "1K",
            "area_m2": 25.5,
            "construction_year_text": "令和4年11月",
            "built_year": 2022,
            "built_month": 11,
            "accesses": [
                {"line_name": "JR山手線", "station_name": "新宿駅", "walk_minutes": 5, "raw_text": "JR山手線 新宿駅 徒歩 5分", "sort_order": 0}
            ],
            "images": [
                {"image_url": "https://www.example.com/img1.jpg", "image_type": "thumbnail", "sort_order": -2}
            ],
            "rent_plans": [
                {
                    "plan_code": "short",
                    "plan_name": "ショート 1～3ヶ月",
                    "duration_text": "1～3ヶ月",
                    "available": 1,
                    "campaign_label": "早割",
                    "original_daily_rent_yen": 4000,
                    "discounted_daily_rent_yen": 3000,
                    "original_total_yen": 120000,
                    "discounted_total_yen": 90000,
                    "total_period_days": 30,
                    "management_fee_daily_yen": 1000,
                    "cleaning_fee_yen": 15000,
                    "raw_text": "早割キャンペーン"
                }
            ],
            "features": [
                {"feature_name": "オートロック", "feature_category": "建物設備", "raw_text": "オートロック"}
            ],
            "campaigns": []
        }
        
        p_id = upsert_normalized_property(mock_data)
        self.assertIsNotNone(p_id)
        
        # Calculate scores
        scores = calculate_property_score(p_id, cursor)
        self.assertIsNotNone(scores)
        self.assertTrue(scores["total_score"] > 0)
        self.assertAlmostEqual(scores["walk_score"], 100.0 * (15 - 5) / (15 - 3), places=2) # 5 mins walk
        
        # Verify shortlist update
        res_sh = db_update_shortlist(p_id, "saved", "Very nice room!")
        self.assertEqual(res_sh["status"], "success")
        
        # Test detail query
        detail = db_get_property_detail(p_id)
        self.assertEqual(detail["shortlist"]["status"], "saved")
        self.assertEqual(detail["shortlist"]["comment"], "Very nice room!")
        self.assertEqual(detail["layout"], "1K")
        self.assertEqual(len(detail["accesses"]), 1)
        self.assertEqual(detail["accesses"][0]["station_name"], "新宿駅")
        
        # Test search
        search_res = db_search_properties({
            "prefecture_name": "東京都",
            "station_names": ["新宿"],
            "max_walk_minutes": 10,
            "min_area_m2": 20.0
        })
        self.assertTrue(len(search_res) > 0)
        self.assertIn("test_room_999", [r["source_property_id"] for r in search_res])
        
        # Test compare
        compare_res = db_compare_properties([p_id])
        self.assertIn("plans", compare_res)
        self.assertEqual(compare_res["shortlist_status"]["test_room_999"], "saved")
        
        # Test anomalies
        anom = detect_anomalies(p_id)
        self.assertNotIn(p_id, anom) # Shinjuku has address and coordinates from geo bound checks
        
        # Cleanup
        cursor.execute("DELETE FROM properties WHERE id = ?", (p_id,))
        conn.commit()
        conn.close()

if __name__ == "__main__":
    unittest.main()
