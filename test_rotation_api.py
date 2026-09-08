#!/usr/bin/env python3
"""Tests for prefecture rotation scheduler / API (GET/POST /api/admin/rotation)."""
import inspect
import os
import sys
import unittest
from unittest import mock

from fastapi.testclient import TestClient

# Ensure src is in import path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import web_server
from web_server import app, run_scrape_v2_task, run_rotation_job


def _clear_rotation_env():
    """Remove all ROTATION_* vars (restored automatically via patch.dict)."""
    for key in [k for k in os.environ if k.startswith("ROTATION_")]:
        os.environ.pop(key)


class TestRotationSourceConfig(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ):
            _clear_rotation_env()
            cfg = web_server._rotation_source_config()
        self.assertEqual([c["id"] for c in cfg], ["bratto", "unionmonthly"])
        by_id = {c["id"]: c for c in cfg}
        self.assertEqual(by_id["bratto"]["cron"], "0 2,14 * * *")
        self.assertEqual(by_id["unionmonthly"]["cron"], "0 5,17 * * *")
        self.assertEqual(by_id["bratto"]["daily_limit"], 500)
        self.assertEqual(by_id["unionmonthly"]["daily_limit"], 500)
        self.assertEqual(by_id["bratto"]["default_est"], 60)

    def test_env_overrides(self):
        with mock.patch.dict(os.environ):
            _clear_rotation_env()
            os.environ["ROTATION_SOURCES"] = "bratto,foo"
            os.environ["ROTATION_CRON_BRATTO"] = "30 1 * * *"
            os.environ["ROTATION_DAILY_LIMIT_FOO"] = "42"
            os.environ["ROTATION_DEFAULT_EST"] = "30"
            cfg = web_server._rotation_source_config()
        by_id = {c["id"]: c for c in cfg}
        self.assertEqual(by_id["bratto"]["cron"], "30 1 * * *")
        # unknown source falls back to generic cron
        self.assertEqual(by_id["foo"]["cron"], "0 8,20 * * *")
        self.assertEqual(by_id["foo"]["daily_limit"], 42)
        self.assertEqual(by_id["bratto"]["default_est"], 30)


class TestRotationApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_get_rotation_status(self):
        response = self.client.get("/api/admin/rotation")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        ids = {s["id"] for s in data.get("sources") or []}
        self.assertIn("bratto", ids)
        self.assertIn("unionmonthly", ids)
        for src in data["sources"]:
            for key in (
                "id",
                "display_name",
                "cron",
                "daily_limit",
                "used_today",
                "default_est",
                "next_batch",
                "prefs",
            ):
                self.assertIn(key, src)
            self.assertIsInstance(src["next_batch"], dict)
            self.assertIn("prefs", src["next_batch"])
            self.assertIn("reason", src["next_batch"])
            for p in src["prefs"]:
                for key in (
                    "slug",
                    "name",
                    "known_total",
                    "last_full_ok_at",
                    "last_run_at",
                    "consecutive_failures",
                    "suppressed",
                    "is_running",
                    "queue_position",
                ):
                    self.assertIn(key, p)
            positions = [p["queue_position"] for p in src["prefs"]]
            self.assertEqual(positions, list(range(1, len(positions) + 1)))
        bratto = next(s for s in data["sources"] if s["id"] == "bratto")
        self.assertEqual(bratto["display_name"], "BraTTo")
        self.assertGreater(len(bratto["prefs"]), 0)

    def test_run_rotation_unknown_source_400(self):
        response = self.client.post("/api/admin/rotation/run", json={"source": "nope"})
        self.assertEqual(response.status_code, 400)

    def test_run_rotation_conflict_409(self):
        old_status = web_server.TASK_STATUS["status"]
        old_task = web_server.TASK_STATUS["current_task"]
        try:
            web_server.TASK_STATUS["status"] = "running"
            web_server.TASK_STATUS["current_task"] = "scrape-v2"
            response = self.client.post(
                "/api/admin/rotation/run", json={"source": "bratto"}
            )
            self.assertEqual(response.status_code, 409)
        finally:
            web_server.TASK_STATUS["status"] = old_status
            web_server.TASK_STATUS["current_task"] = old_task

    def test_run_rotation_started(self):
        with mock.patch.object(web_server, "run_rotation_job") as mock_job:
            with mock.patch.dict(os.environ):
                _clear_rotation_env()
                response = self.client.post(
                    "/api/admin/rotation/run", json={"source": "bratto"}
                )
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data.get("status"), "started")
                self.assertEqual(data.get("task"), "rotation")
                self.assertEqual(data.get("source"), "bratto")
                mock_job.assert_called_once_with(
                    "bratto", daily_limit=500, default_est=60
                )

    def test_run_rotation_job_skips_when_task_running(self):
        old_status = web_server.TASK_STATUS["status"]
        old_log_len = len(web_server.TASK_STATUS["logs"])
        try:
            web_server.TASK_STATUS["status"] = "running"
            run_rotation_job("bratto")
            logs = "".join(web_server.TASK_STATUS["logs"][old_log_len:])
            self.assertIn("skipped: another task running", logs)
        finally:
            web_server.TASK_STATUS["status"] = old_status
            del web_server.TASK_STATUS["logs"][old_log_len:]


class TestRunScrapeV2TaskSignature(unittest.TestCase):
    def test_rotation_defaults_false(self):
        sig = inspect.signature(run_scrape_v2_task)
        self.assertIn("rotation", sig.parameters)
        self.assertIs(sig.parameters["rotation"].default, False)


if __name__ == "__main__":
    unittest.main()
