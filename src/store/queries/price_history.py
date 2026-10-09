"""価格履歴 / 価格変動トレンド系クエリ."""

from __future__ import annotations

import psycopg
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

from domain.tz import JST

from store.pg import open_connection
from store.source_catalog import SOURCE_CATALOG, SOURCE_DISPLAY


# 価格破損値ガードの比帯域 (SSOT)。Python 側 _guard_price_history と
# SQL 側 _trend_ctes の guarded CTE の双方がこの定数を参照する。
# unionmonthly parser v1.0 低値破損の検証結果に基づく (0.25x〜4x 参照値比)。
PRICE_GUARD_MIN_RATIO = 0.25
PRICE_GUARD_MAX_RATIO = 4.0


def fallback_ref(values: Iterable[Any]) -> float | None:
    """ref 無効時の代替参照値 = 系列の正値中央値 (ガード規則の唯一の実装).

    母集団は対象物件の全期間の正値スナップ値 (詳細APIの履歴窓と同一)。
    statistics.median と同じ扱い (奇数件は中央1件、偶数件は中央2件の平均)。
    正値が1件も無い場合は None を返し、参照値を根拠にできないため
    呼び出し側は系列全体を除外する。
    """
    positive = [v for v in values if isinstance(v, (int, float)) and v > 0]
    return statistics.median(positive) if positive else None


def _guard_condition_sql(expr_v: str, expr_ref: str) -> str:
    """guarded CTE 用の破損値除外条件 (_guard_price_history と同一規則).

    帯域は PRICE_GUARD_MIN_RATIO / PRICE_GUARD_MAX_RATIO を SSOT とする。
    expr_ref のフォールバック (COALESCE の第2項) は temp table guard_fallback
    の ref 列 (fb.ref) を参照する。同テーブルの値は get_price_trend が
    fallback_ref() (中央値規則の唯一実装) で Python 側から算出して投入する
    ため、この条件は _trend_ctes の guarded CTE 専用。
    """
    ref = f"COALESCE(NULLIF({expr_ref}, 0), fb.ref)"
    return (
        f"WHERE {ref} IS NOT NULL\n"
        f"      AND {expr_v} > 0\n"
        f"      AND {expr_v} >= {PRICE_GUARD_MIN_RATIO} * {ref}\n"
        f"      AND {expr_v} <= {PRICE_GUARD_MAX_RATIO} * {ref}"
    )


def _guard_price_history(
    snap_rows: list[dict[str, Any]],
    ref: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """価格履歴から破損値を除外する(検証済みガード: v > 0 かつ
    PRICE_GUARD_MIN_RATIO*ref <= v <= PRICE_GUARD_MAX_RATIO*ref。帯域定数は
    本モジュール上部の SSOT を参照).

    ref は properties.catalog_rent_per_day_yen(現行値)。無効( NULL / 0 以下 )の
    場合は fallback_ref()(系列自身の正値中央値)にフォールバックする。
    unionmonthly parser v1.0 の
    低値破損(~2万行)が価格履歴UIに混入するのを防ぐのが目的で、除外件数は
    price_history_meta として FE に開示する。
    """
    if not isinstance(ref, (int, float)) or ref <= 0:
        ref = fallback_ref(r.get("catalog_rent_per_day_yen") for r in snap_rows)

    guarded: list[dict[str, Any]] = []
    dropped = 0
    for r in snap_rows:
        v = r.get("catalog_rent_per_day_yen")
        if (
            not isinstance(v, (int, float))
            or v <= 0
            or ref is None
            or not (PRICE_GUARD_MIN_RATIO * ref <= v <= PRICE_GUARD_MAX_RATIO * ref)
        ):
            dropped += 1
            continue
        guarded.append(
            {
                "scraped_at": r["scraped_at"],
                "min_discounted_daily_rent_yen": v,
                "min_discounted_monthly_total_yen": r.get("min_discounted_monthly_total_yen"),
            }
        )
    meta = {
        "total_count": len(snap_rows),
        "dropped_count": dropped,
        "first_at": guarded[0]["scraped_at"] if guarded else None,
        "last_at": guarded[-1]["scraped_at"] if guarded else None,
    }
    return guarded, meta


# 価格変動推移の共通CTE: 品質ガード(_guard_price_history と同じ規則)適用後、
# 同日は最新行を代表値とする。
#
# ref フォールバックの中身 (中央値の計算) は SQL 側に置かず、
# _load_guard_fallbacks が Python 側 fallback_ref() で算出した値を
# temp table 経由で渡す (規則の SSOT は Python のみ)。
def _trend_ctes(prefecture: bool) -> str:
    """価格変動推移の共通 CTE を組み立てる.

    prefecture=True のとき base の WHERE に県絞り込み (AND p.prefecture_name = %s)
    を追加する。プレースホルダは cutoff の直後に都道府県名が続くため、この CTE を
    使う全クエリ (rows / counts / carried_rows) で同じ params タプルを渡すこと。
    guard_fallback は同一接続内で _load_guard_fallbacks を先に呼んでおくこと。
    """
    pref_clause = "\n      AND p.prefecture_name = %s" if prefecture else ""
    return f"""
WITH base AS (
    SELECT s.property_id AS property_id,
           (s.scraped_at AT TIME ZONE 'Asia/Tokyo')::date AS d,
           s.scraped_at AS scraped_at,
           s.catalog_rent_per_day_yen AS v,
           s.is_active AS is_active,
           p.source_site AS source_site,
           p.catalog_rent_per_day_yen AS ref
    FROM property_snapshots s
    JOIN properties p ON p.id = s.property_id
    WHERE s.scraped_at >= %s{pref_clause}
),
guarded AS (
    SELECT b.property_id, b.d, b.scraped_at, b.v, b.source_site, b.is_active
    FROM base b
    LEFT JOIN guard_fallback fb ON fb.property_id = b.property_id
    {_guard_condition_sql("b.v", "b.ref")}
)
"""


def _load_guard_fallbacks(conn: psycopg.Connection) -> None:
    """ref 無効物件の代替参照値 (fallback_ref) を temp table へ投入する.

    guarded CTE は ref が無効 (NULL / 0) の物件だけ guard_fallback.ref に
    フォールバックする。該当物件が無ければ現在の本番常態どおり空のまま
    (JOIN は NULL を返し、参照値を根拠にできない行は除外される)。
    中央値の母集団は「その物件の全期間の正値スナップ行」で、詳細APIの
    _guard_price_history と同一窓。temp table は接続単位なので呼び出し毎に
    作り直す。
    """
    conn.execute("DROP TABLE IF EXISTS pg_temp.guard_fallback")
    conn.execute(
        "CREATE TEMP TABLE guard_fallback ("
        "property_id INTEGER PRIMARY KEY, ref REAL)"
    )
    rows = conn.execute(
        """
        SELECT s.property_id AS property_id, s.catalog_rent_per_day_yen AS v
        FROM properties p
        JOIN property_snapshots s ON s.property_id = p.id
        WHERE (p.catalog_rent_per_day_yen IS NULL OR p.catalog_rent_per_day_yen <= 0)
          AND s.catalog_rent_per_day_yen > 0
        """
    ).fetchall()
    if not rows:
        return
    by_pid: dict[int, list[Any]] = defaultdict(list)
    for r in rows:
        by_pid[r["property_id"]].append(r["v"])
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO guard_fallback (property_id, ref) VALUES (%s, %s)",
            [(pid, fallback_ref(vals)) for pid, vals in by_pid.items()],
        )

# 前進補完(キャリーフォワード)の鮮度窓(日)。ローテーションは直近7日でほぼ全物件を
# 巡回するため、7日以内の取得値を「その日時点での既知値」とみなす。
_CARRY_FORWARD_WINDOW_DAYS = 7

# guarded から同日重複を除いた物件単位の日次代表値
_TREND_DAILY_CTES = """
, latest AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY property_id, d ORDER BY scraped_at DESC
    ) AS rn
    FROM guarded
),
daily AS (
    SELECT property_id, d, source_site, v
    FROM latest
    WHERE rn = 1 AND COALESCE(is_active, TRUE)
)
"""

# 当日取得分モードの元データ: 直前の代表値比(LAG)付き
_TREND_CHG_SQL = _TREND_DAILY_CTES + """
, chg AS (
    SELECT d, source_site, v,
           LAG(v) OVER (PARTITION BY property_id ORDER BY d) AS prev_v
    FROM daily
)
SELECT d, source_site, v, prev_v FROM chg ORDER BY d
"""

# 前進補完推計モード: 各物件の代表値を「次回取得日の前日 かつ 取得日+窓日数」まで
# 前進補間する(セグメント化により物件×日の重複が構造的に発生しないため dedup 不要)。
# 中央値は窓関数の大規模ソートを避けるため「日付×サイト×値」のヒストグラム
# (COUNT)まで SQL 側で畳み、順位の特定は Python 側で行う。サイト別と全サイト分は
# UNION ALL で1回の走査から両方集計する。
_offs_values = ",".join(f"({i})" for i in range(_CARRY_FORWARD_WINDOW_DAYS))
_TREND_CARRIED_SQL = _TREND_DAILY_CTES + f"""
, seg AS (
    SELECT property_id, source_site, v, d AS src_d,
           LEAST(
             COALESCE((LEAD(d) OVER (PARTITION BY property_id ORDER BY d))::date - 1, DATE '9999-12-31'),
             (d::date + {_CARRY_FORWARD_WINDOW_DAYS - 1}),
             (now() AT TIME ZONE 'Asia/Tokyo')::date
           ) AS seg_end
    FROM daily
),
dates(off) AS (VALUES {_offs_values}),
carried AS (
    SELECT (s.src_d::date + x.off)::text AS d,
           s.property_id, s.source_site, s.v
    FROM seg s CROSS JOIN dates x
    WHERE (s.src_d::date + x.off) <= s.seg_end
)
SELECT d, g, v, COUNT(*) AS n
FROM (
    SELECT d, source_site AS g, v FROM carried
    UNION ALL
    SELECT d, '__all__' AS g, v FROM carried
)
GROUP BY d, g, v
"""


def _hist_median_avg(hist: dict[int, int]) -> tuple[int, int, int]:
    """値→件数のヒストグラムから (中央値, 平均, 総件数) を算出する.

    SQLite 移行前の AVG(v) FILTER(rk = cnt/2+1 ...) と同じ順位の値を採用する
    (奇数は中央1件、偶数は中央2件の平均)。ヒストグラムは空でないこと。
    """
    total = sum(hist.values())
    positions = {total // 2, total // 2 + 1}
    picked: dict[int, int] = {}
    acc = 0
    avg_sum = 0
    for v in sorted(hist):
        n = hist[v]
        acc += n
        avg_sum += v * n
        for p in positions:
            if p not in picked and acc >= p:
                picked[p] = v
        if len(picked) == len(positions):
            break
    if total % 2 == 1:
        median = picked[total // 2 + 1]
    else:
        median = (picked[total // 2] + picked[total // 2 + 1]) / 2
    return round(median), round(avg_sum / total), total


def get_price_trend(days: int = 90, prefecture_name: str | None = None) -> dict[str, Any]:
    """日次の価格変動推移を全プロバイダ分まとめて返す.

    2つのモードの系列を返す(FE側で「すべて/プロバイダ別」「モード」を切替):
    - scraped(当日取得分): その日に取得成功した物件のみの日次集計。取得構成
      (サイト/県)の影響で日次の数値が変動する。
    - carried(前進補完推計): 各物件の「その日時点での最終既知値」
      (直近 _CARRY_FORWARD_WINDOW_DAYS 日以内の取得値)を母集団全件に適用した
      市場トレンド推計。中央値/平均/掲載物件数の主指標はこちら。
    値下げ/値上げ件数は「当日取得した値で確認された変動」で両モード共通。
    prefecture_name を指定すると物件分析モーダルの「同都道府県の市場中央値」用に
    その県の物件のみで集計する。空文字列は未指定(全県)と同じ扱い。
    """
    with open_connection() as conn:
        cutoff_date = (datetime.now() - timedelta(days=days)).date().isoformat()
        # 空文字列も全県扱いへ正規化する
        pref = (prefecture_name or "").strip() or None
        # ref 無効物件のフォールバック参照値を先に解決してから CTE を実行する
        _load_guard_fallbacks(conn)
        ctes = _trend_ctes(pref is not None)
        params = (cutoff_date, pref) if pref else (cutoff_date,)

        rows = conn.execute(ctes + _TREND_CHG_SQL, params).fetchall()
        counts = conn.execute(
            ctes
            + """
            SELECT (SELECT COUNT(*) FROM base) AS base_count,
                   (SELECT COUNT(*) FROM guarded) AS guarded_count
            """,
            params,
        ).fetchone()
        carried_rows = conn.execute(ctes + _TREND_CARRIED_SQL, params).fetchall()

    # (日付, プロバイダ) ごとに値と変動を集約(当日取得分)。
    # d は base CTE の date (Phase 6c) なので carried 側 (::text) とキーを
    # 揃えるため isoformat へ正規化する
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r["d"].isoformat() if hasattr(r["d"], "isoformat") else str(r["d"]),
               r["source_site"] or "?")
        cell = cells.setdefault(key, {"values": [], "down": 0, "up": 0})
        cell["values"].append(r["v"])
        pv = r["prev_v"]
        if pv is not None:
            if r["v"] < pv:
                cell["down"] += 1
            elif r["v"] > pv:
                cell["up"] += 1

    # 前進補完側の集計結果(g = サイトid か '__all__')。ヒストグラムから統計量を算出
    carried_hist: dict[tuple[str, str], dict[int, int]] = defaultdict(dict)
    for r in carried_rows:
        carried_hist[(r["d"], r["g"])][r["v"]] = r["n"]
    carried_cells: dict[tuple[str, str], dict[str, Any]] = {
        key: dict(zip(("median", "avg", "count"), _hist_median_avg(hist)))
        for key, hist in carried_hist.items()
    }

    # 変動件数は当日の取得で確認されたものなので、両モードで同じ値を使う
    day_changes: dict[str, dict[str, int]] = defaultdict(lambda: {"down": 0, "up": 0})
    for (d, _s), cell in cells.items():
        day_changes[d]["down"] += cell["down"]
        day_changes[d]["up"] += cell["up"]

    def build_scraped_series(sites: set[str] | None) -> list[dict[str, Any]]:
        # 「すべて」では同一日の複数サイトを1点へ統合するため、日付ごとに集約する
        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (d, site), cell in cells.items():
            if sites is None or site in sites:
                by_date[d].append(cell)
        out = []
        for d in sorted(by_date):
            entries = by_date[d]
            vals = [v for e in entries for v in e["values"]]
            out.append(
                {
                    "date": d,
                    "median": round(statistics.median(vals)),
                    "avg": round(statistics.fmean(vals)),
                    "count": len(vals),
                    "down": sum(e["down"] for e in entries),
                    "up": sum(e["up"] for e in entries),
                }
            )
        return out

    def build_carried_series(sites: set[str] | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for (d, g), c in sorted(carried_cells.items()):
            if sites is None:
                if g != "__all__":
                    continue
                ch = day_changes[d]
            else:
                if g not in sites:
                    continue
                ch = cells.get((d, g), {"down": 0, "up": 0})
            out.append({"date": d, **c, "down": ch["down"], "up": ch["up"]})
        return out

    catalog_order = {s["id"]: i for i, s in enumerate(SOURCE_CATALOG)}
    present_sites = sorted(
        {site for (_d, site) in cells},
        key=lambda s: (catalog_order.get(s, len(catalog_order)), s),
    )

    return {
        "days": days,
        "carried_window_days": _CARRY_FORWARD_WINDOW_DAYS,
        "generated_at": datetime.now(JST),
        "providers": [
            {"id": sid, "display_name": SOURCE_DISPLAY.get(sid, sid)}
            for sid in present_sites
        ],
        "series": {
            "carried": {
                "all": build_carried_series(None),
                "by_site": {sid: build_carried_series({sid}) for sid in present_sites},
            },
            "scraped": {
                "all": build_scraped_series(None),
                "by_site": {sid: build_scraped_series({sid}) for sid in present_sites},
            },
        },
        "meta": {
            "snapshot_rows": counts["base_count"],
            "guarded_rows": counts["guarded_count"],
            "excluded_rows": counts["base_count"] - counts["guarded_count"],
        },
    }
