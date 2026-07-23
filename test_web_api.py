import unittest
import os
import sys
from fastapi.testclient import TestClient

# Ensure src is in import path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from web_server import app
from database import get_db_connection

class TestWebAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We will use the existing database for read-only tests,
        # but for shortlist write tests we will make sure to update and restore.
        cls.client = TestClient(app)
        
    def test_root_route(self):
        """Test that root route serves map_viewer.html"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("yadokariMut", response.text)

    def test_geojson_api(self):
        """Test that /api/geojson returns valid FeatureCollection"""
        response = self.client.get("/api/geojson?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("type"), "FeatureCollection")
        self.assertIsInstance(data.get("features"), list)

    def test_geojson_includes_prefecture_name(self):
        """GeoJSON properties should include prefecture_name for UI/AI filters."""
        response = self.client.get("/api/geojson?limit=3")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        features = data.get("features") or []
        if not features:
            self.skipTest("No geojson features available")
        props = features[0].get("properties") or {}
        self.assertIn("prefecture_name", props)

    def test_admin_status_api(self):
        """Test that /api/admin/status returns database statistics"""
        response = self.client.get("/api/admin/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("db_stats", data)
        self.assertIn("task_status", data)
        self.assertIn("total_properties", data["db_stats"])

    def test_shortlist_update_api(self):
        """Test that updating property shortlist status works"""
        # Fetch one property ID from the database first
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM properties LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            self.skipTest("No properties in database to test shortlist update.")
            
        prop_id = row["id"]
        
        # Test updating to 'saved'
        response = self.client.post(
            f"/api/properties/{prop_id}/shortlist",
            json={"status": "saved", "comment": "API Test Comment"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("shortlist_status"), "saved")
        
        # Verify in DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, comment FROM shortlists WHERE property_id = ?", (prop_id,))
        sh_row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(sh_row)
        self.assertEqual(sh_row["status"], "saved")
        self.assertEqual(sh_row["comment"], "API Test Comment")
        
        # Restore status to hide or delete
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM shortlists WHERE property_id = ?", (prop_id,))
        conn.commit()
        conn.close()

if __name__ == "__main__":
    unittest.main()
