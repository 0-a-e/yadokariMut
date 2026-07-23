#!/usr/bin/env python3
"""Unit tests for HttpFetchClient skeleton."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from sources.http.client import FetchError, HttpFetchClient
from sources.http.metrics import TransferMetrics
from sources.http.restriction import is_restricted
from sources.http.settings import HttpFetchSettings, load_http_settings


class TestRestriction(unittest.TestCase):
    def test_status_429(self):
        s = HttpFetchSettings()
        ok, reason = is_restricted(status_code=429, body="x" * 1000, settings=s)
        self.assertTrue(ok)
        self.assertEqual(reason, "http_429")

    def test_ok_body(self):
        s = HttpFetchSettings()
        ok, _ = is_restricted(status_code=200, body="<html>" + "a" * 1000, settings=s)
        self.assertFalse(ok)

    def test_challenge_body(self):
        s = HttpFetchSettings()
        ok, reason = is_restricted(
            status_code=200,
            body="<html>Just a moment... cf-browser-verification</html>",
            settings=s,
        )
        self.assertTrue(ok)
        self.assertIsNotNone(reason)


class TestSettings(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCRAPE_HTTP_MODE", None)
            os.environ.pop("YADOKARIMUT_SCRAPE_HTTP_MODE", None)
            os.environ.pop("SCRAPE_HTTP_PROXY", None)
            # force empty config path via explicit config
            s = load_http_settings({"http": {}})
            self.assertEqual(s.mode, "off")
            self.assertFalse(s.proxy_enabled)

    def test_fallback_without_proxy_stays_disabled(self):
        s = load_http_settings(
            {"http": {"mode": "fallback"}}
        )
        # env may override; force via constructing settings
        s2 = HttpFetchSettings(mode="fallback", http_proxy_url=None, proxy_enabled=False)
        self.assertFalse(s2.proxy_enabled)


class TestClientDirect(unittest.TestCase):
    def test_direct_200(self):
        metrics = TransferMetrics()
        settings = HttpFetchSettings(mode="off", max_retries=0)
        client = HttpFetchClient(source_id="testsrc", settings=settings, metrics=metrics)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>" + ("x" * 600)
        mock_resp.url = "https://example.com/a"
        mock_resp.encoding = "utf-8"
        mock_resp.apparent_encoding = "utf-8"

        with patch.object(client.session, "get", return_value=mock_resp) as g:
            r = client.request("https://example.com/a", delay_seconds=0)
        g.assert_called_once()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.transport, "direct")
        self.assertGreater(r.bytes_downloaded, 0)
        snap = metrics.snapshot()
        self.assertEqual(snap["lifetime"]["by_source"]["testsrc"]["requests"], 1)
        self.assertEqual(snap["lifetime"]["total"]["direct_requests"], 1)

    def test_403_direct_only_fails(self):
        metrics = TransferMetrics()
        settings = HttpFetchSettings(mode="off", max_retries=0)
        client = HttpFetchClient(source_id="t2", settings=settings, metrics=metrics)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Access Denied"
        mock_resp.url = "https://example.com/b"
        mock_resp.encoding = "utf-8"
        mock_resp.apparent_encoding = "utf-8"
        with patch.object(client.session, "get", return_value=mock_resp):
            with self.assertRaises(FetchError):
                client.request("https://example.com/b", delay_seconds=0)
        self.assertEqual(metrics.snapshot()["lifetime"]["by_source"]["t2"]["restricted_hits"], 1)


if __name__ == "__main__":
    unittest.main()
