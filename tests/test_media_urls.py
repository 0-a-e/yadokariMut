#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for sources.media_urls (取得時URL正規化のSSOT・docs/media-storage-rustfs-plan.md §2.6)。"""

from sources.media_urls import resolve_media_url

_WRAPPER = (
    "https://www.unionmonthly.jp/img_out.php"
    "?img_data=http://unionmonthly-img.jp/img/room/10000/3368/r2.jpg"
)
_INNER = "http://unionmonthly-img.jp/img/room/10000/3368/r2.jpg"


def test_unwrap_unionmonthly_wrapper():
    assert resolve_media_url("unionmonthly", _WRAPPER) == _INNER


def test_direct_unionmonthly_url_unchanged():
    assert resolve_media_url("unionmonthly", _INNER) == _INNER


def test_wrapper_without_img_data_unchanged():
    url = "https://www.unionmonthly.jp/img_out.php?foo=1"
    assert resolve_media_url("unionmonthly", url) == url


def test_wrapper_with_non_http_img_data_unchanged():
    url = "https://www.unionmonthly.jp/img_out.php?img_data=%2Fetc%2Fpasswd"
    assert resolve_media_url("unionmonthly", url) == url


def test_unknown_site_identity():
    # bratto 等の未知サイトは無処理(サイト別知識の追加は _RESOLVERS のみ)
    assert resolve_media_url("bratto", _WRAPPER) == _WRAPPER
    assert resolve_media_url(None, _WRAPPER) == _WRAPPER


def test_unionmonthly_other_path_unchanged():
    url = "https://www.unionmonthly.jp/room/12345/"
    assert resolve_media_url("unionmonthly", url) == url
