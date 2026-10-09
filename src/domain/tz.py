"""Asia/Tokyo タイムゾーンの正本 (Phase 6c・D8)。

DB の timestamptz 列は naive JST 文字列 (naive isoformat) で書き込まれ、
セッション TZ (store.pg の接続 options) で Asia/Tokyo 解釈される。
Python 側で aware な「現在時刻」を生成する必要がある箇所
(API 直列化・時刻比較)はこの JST を使う(表記は "+09:00" 付き)。
"""

from __future__ import annotations

from datetime import timedelta, timezone

JST = timezone(timedelta(hours=9), name="Asia/Tokyo")
