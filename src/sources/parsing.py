"""スカラー値テキストパースの共通層 (bratto / unionmonthly 共有)。

金額・面積・徒歩分数・駅/路線分割・キャンペーン期間の日付・築年(和暦/西暦)
といった、ソースに依存しない「テキスト → スカラー」変換をここに集約する。
HTML 構造の解釈(セレクタやテーブル走査)は各ソースのパーサ側の責務。

金額は bratto の ``parse_money`` を正として統合している
(「円」直前の数値を優先するため ``(月 75,000円/30日)`` のような
  期間付き総額表記でも 75000 を返す)。
築年は昭和/平成/令和の和暦にも対応し、unionmonthly の西暦専用実装を置換した
(和暦表記の物件で built_year が欠落する問題の解消)。
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime


def parse_money(text) -> int | None:
    """金額テキストから円建て整数を取り出す。

    「円」の直前の数値を優先するため、``(月 75,000円/30日)`` のような
    期間接尾辞付き表記も 75000 として解釈する。

    Examples:
      "4,900円/日" -> 4900
      "(月 75,000円/30日)" -> 75000
      "(週 14,350円/7日)" -> 14350
      "-1,080,000円/30日" -> -1080000
      "16,500" -> 16500
    """
    if not text:
        return None
    match = re.search(r'(-?[\d,]+)\s*円', text)
    if match:
        return int(match.group(1).replace(',', ''))
    cleaned = re.sub(r'[^\d-]', '', text)
    if cleaned in ('', '-'):
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_area(text) -> float | None:
    """面積テキストから数値を取り出す (例: "19.16㎡" -> 19.16)。"""
    if not text:
        return None
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    return float(match.group(1)) if match else None


def parse_walk_minutes(text) -> int | None:
    """徒歩分数テキストから整数を取り出す (例: "徒歩 5分" -> 5)。"""
    if not text:
        return None
    match = re.search(r'(\d+)\s*分', text)
    return int(match.group(1)) if match else None


def parse_dates_from_text(text: str, default_year: int = None) -> tuple[str | None, str | None]:
    """日本語のキャンペーン期間テキストから (開始日, 終了日) の ISO 日付を取り出す。

    対応フォーマット:
      - 2026年5月21日～2026年6月21日
      - 2026年5月1日から5月31日まで (年を終日に引き継ぐ)
      - 2026年5月 (月全体)
      - 5月中 (現在年/指定年の月全体)
    """
    if not text:
        return None, None

    if default_year is None:
        default_year = datetime.now().year

    # 範囲セパレータと空白を正規化
    text = re.sub(r'\s+', '', text)

    # 1. 年月日 / 月日のマッチ
    # Pattern: (Group 1: Year)? (Group 2: Month) (Group 3: Day)
    pattern_ymd = r'(?<!\d)(?:(\d{4})[年/\-])?(\d{1,2})[月/\-](\d{1,2})日?(?!\d)'
    matches_ymd = re.findall(pattern_ymd, text)

    parsed_dates = []
    current_year = default_year

    if matches_ymd:
        for y, m, d in matches_ymd:
            month = int(m)
            day = int(d)
            if y:
                current_year = int(y)
            # 月日の妥当性検証 (電話番号等の誤検出防止)
            if 1 <= month <= 12 and 1 <= day <= 31:
                # 存在しない日 (例: 2月31日) は月末にクランプ
                last = calendar.monthrange(current_year, month)[1]
                day = min(day, last)
                parsed_dates.append((current_year, month, day))

    if len(parsed_dates) >= 2:
        starts_on = f"{parsed_dates[0][0]:04d}-{parsed_dates[0][1]:02d}-{parsed_dates[0][2]:02d}"
        ends_on = f"{parsed_dates[1][0]:04d}-{parsed_dates[1][1]:02d}-{parsed_dates[1][2]:02d}"
        return starts_on, ends_on
    elif len(parsed_dates) == 1:
        starts_on = f"{parsed_dates[0][0]:04d}-{parsed_dates[0][1]:02d}-{parsed_dates[0][2]:02d}"
        # 「〜月末」「当月中」: 開始日1件 + 中 → その月の月末まで
        if re.search(r'中|まで|末日', text):
            y, m, _d = parsed_dates[0]
            last_day = calendar.monthrange(y, m)[1]
            ends_on = f"{y:04d}-{m:02d}-{last_day:02d}"
            return starts_on, ends_on
        return starts_on, None

    # 2. 年月のマッチ
    # Pattern: (Group 1: Year) (Group 2: Month)
    # e.g., 2026年5月, 2026/05
    pattern_ym = r'(?<!\d)(\d{4})[年/](\d{1,2})月?(?!\d)'
    matches_ym = re.findall(pattern_ym, text)

    if matches_ym:
        year = int(matches_ym[0][0])
        month = int(matches_ym[0][1])
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            starts_on = f"{year:04d}-{month:02d}-01"
            ends_on = f"{year:04d}-{month:02d}-{last_day:02d}"
            if len(matches_ym) >= 2:
                eyear = int(matches_ym[1][0])
                emonth = int(matches_ym[1][1])
                if 1 <= emonth <= 12:
                    elast_day = calendar.monthrange(eyear, emonth)[1]
                    ends_on = f"{eyear:04d}-{emonth:02d}-{elast_day:02d}"
            return starts_on, ends_on

    # 3. 月のみ + 中 (例: 5月中にご契約) は default_year で解釈
    m_mid = re.search(r'(?<!\d)(\d{1,2})月中', text)
    if m_mid:
        month = int(m_mid.group(1))
        if 1 <= month <= 12:
            last_day = calendar.monthrange(default_year, month)[1]
            return (
                f"{default_year:04d}-{month:02d}-01",
                f"{default_year:04d}-{month:02d}-{last_day:02d}",
            )

    return None, None


def parse_japanese_era(text) -> tuple[int | None, int | None]:
    """築年テキストを (西暦年, 月) に解釈する。

    和暦 (例: "昭和59年7月" -> (1984, 7), "令和元年5月" -> (2019, 5)) と
    西暦 (例: "200612" -> (2006, 12), "2006年12月" -> (2006, 12),
    "2024年" -> (2024, None)) の両方に対応する。
    解釈できない場合は (None, None)。
    """
    if not text:
        return None, None
    text = text.strip()

    # 6桁の西暦数字 e.g. "200612"
    if re.match(r'^\d{6}$', text):
        return int(text[:4]), int(text[4:])

    # 西暦年月 e.g. "2006年12月"
    west_match = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月', text)
    if west_match:
        return int(west_match.group(1)), int(west_match.group(2))

    west_year_only = re.search(r'(\d{4})\s*年', text)
    if west_year_only:
        return int(west_year_only.group(1)), None

    # 和暦
    era_match = re.search(r'(昭和|平成|令和)\s*(\d+|元)\s*年\s*(?:(\d{1,2})\s*月)?', text)
    if era_match:
        era = era_match.group(1)
        year_str = era_match.group(2)
        month_str = era_match.group(3)

        year_num = 1 if year_str == "元" else int(year_str)

        if era == "昭和":
            base = 1925
        elif era == "平成":
            base = 1988
        elif era == "令和":
            base = 2018
        else:
            return None, None

        year = base + year_num
        month = int(month_str) if month_str else None
        return year, month

    return None, None


def split_access(raw: str) -> tuple[str | None, str | None, int | None]:
    """交通文字列を (路線名, 駅名, 徒歩分数) へ寛容に分割する。

    unionmonthly の "JR山手線　渋谷駅　徒歩8分" 形式を想定。
    全角空白・スラッシュ等の揺れに耐え、路線名が取れない場合は None を返す。
    """
    walk = None
    m = re.search(r"徒歩\s*(\d+)\s*分", raw)
    if m:
        walk = int(m.group(1))
    station = None
    m2 = re.search(r"([^\s　]+駅)", raw)
    if m2:
        station = m2.group(1)
    line = None
    if station and station in raw:
        line = raw.split(station)[0].strip(" 　/")
        if not line:
            line = None
    return line, station, walk


def parse_access_parts(raw: str) -> tuple[str | None, str | None, int | None]:
    """bratto 形式の交通文字列を (路線名, 駅名, 徒歩分数) へ分割する。

    "京成本線 千住大橋駅 徒歩 4分" を厳密に解釈し、失敗した場合は
    徒歩分数と駅名を緩く拾うフォールバックに切り替える。
    bratto normalize の歴史的挙動をそのまま移設しており、
    フォールバック時の路線名は空文字列になり得る点に注意。
    """
    match = re.match(r'^(.*?)\s+(\S+駅)\s+徒歩\s*(\d+)\s*分', raw)
    if match:
        return match.group(1).strip(), match.group(2).strip(), int(match.group(3))
    walk = parse_walk_minutes(raw)
    line = None
    station = None
    station_match = re.search(r'(\S+駅)', raw)
    if station_match:
        station = station_match.group(1)
        line = raw.split(station)[0].strip()
    return line, station, walk
