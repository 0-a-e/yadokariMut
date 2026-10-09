"""建物の名寄せと代表値集約 (docs/building-aggregation-design.md §4/§5/§7).

データの正本は部屋行(properties)のまま変更せず、buildings/building_names を
導出キャッシュとして保守する。3 つの入口を持つ:

1. ``assign_building``            — スクレイプ時(upsert トランザクション内)の
                                     同一 address_key 決定的割当(§5 第 1 段)
2. ``run_identity_batch``         — 日次バッチ/CLI。未割当の割当・クロスソース
                                     名寄せ(address_key 完全一致=割当と同一条理)・
                                     dry-run レポート・コンフリクト検出(§5 第 2 段)
3. ``merge_buildings`` / ``split_building`` — 手動オーバーライド CLI

循環 import を避けるため本モジュールは store.repository を import しない
(repository が本モジュールを呼ぶため)。時刻は引数で受け取る。
"""

from __future__ import annotations

import psycopg
from datetime import datetime
from typing import Any

from domain.building_identity import extract_building_name, normalize_address_key
from domain.pricing import to_per_day


def _now() -> str:
    return datetime.now().isoformat()


# ----------------------------------------------------------------------
# 集約ヘルパー(§7 代表値集約規則)
# ----------------------------------------------------------------------


def _majority(values: list[Any]) -> Any:
    """None を除外した多数決(同数は先出)。builds §7 の代表値規則の基本形。"""
    counts: dict[Any, int] = {}
    order: list[Any] = []
    for v in values:
        if v is None:
            continue
        if v not in counts:
            order.append(v)
            counts[v] = 0
        counts[v] += 1
    if not counts:
        return None
    return max(order, key=lambda v: counts[v])


def _majority_coords(
    rooms: list[dict[str, Any]],
) -> tuple[float, float, str | None, float | None] | None:
    """(lat,lng) の多数決。同数は geocode_confidence 最大(§5 代表座標)。

    実測では同一住所内の座標不一致は bratto 2% / union 0.3% のため、
    多数決で確定しつつ_confidence によるタイブレークを備える。
    """
    groups: dict[tuple[float, float], dict[str, Any]] = {}
    order: list[tuple[float, float]] = []
    for r in rooms:
        lat, lng = r.get("lat"), r.get("lng")
        if lat is None or lng is None:
            continue
        key = (lat, lng)
        if key not in groups:
            groups[key] = {"count": 0, "conf": None, "source": None}
            order.append(key)
        g = groups[key]
        g["count"] += 1
        conf = r.get("geocode_confidence")
        if conf is not None and (g["conf"] is None or conf > g["conf"]):
            g["conf"] = conf
            g["source"] = r.get("geocode_source")
    if not groups:
        return None
    best = max(
        order,
        key=lambda k: (groups[k]["count"], groups[k]["conf"] or -1.0),
    )
    g = groups[best]
    return (best[0], best[1], g["source"], g["conf"])


def _min_rent_of_rooms(
    cur: psycopg.Cursor, room_ids: list[int]
) -> tuple[int | None, int | None]:
    """建物内部屋の price_plans から最安日額/30日総額を計算(キャッシュ用).

    キャッシュは ORDER BY / ページング用途のため campaign 実効値解決は含まない
    (割引後日額+共益費日額の最小)。配信時の厳密値は queries.buildings が
    units の rent_plans(実効値解決済み)から計算する。
    """
    min_daily: int | None = None
    min_total: int | None = None
    for start in range(0, len(room_ids), 900):
        chunk = room_ids[start : start + 900]
        ph = ",".join("%s" for _ in chunk)
        rows = cur.execute(
            f"SELECT presentation_unit, rent_current_yen, rent_original_yen,"
            f" management_yen, available FROM price_plans WHERE property_id IN ({ph})",
            chunk,
        ).fetchall()
        for row in rows:
            if not row["available"]:
                continue
            unit = row["presentation_unit"] or "per_day"
            daily = to_per_day(row["rent_current_yen"], unit)
            if daily is None:
                daily = to_per_day(row["rent_original_yen"], unit)
            mgmt = to_per_day(row["management_yen"], unit)
            if daily is None or daily <= 0:
                continue
            total = (daily + mgmt) * 30 if mgmt is not None else None
            if min_daily is None or daily < min_daily:
                min_daily = daily
                min_total = total
    return min_daily, min_total


def _source_representative_names(
    rooms: list[dict[str, Any]],
) -> dict[str, str]:
    """ソースごとの代表建物名(ソース内多数決)。building_names の正本候補。"""
    per_source: dict[str, list[str | None]] = {}
    for r in rooms:
        name = extract_building_name(r["source_site"], r["title"])
        per_source.setdefault(r["source_site"], []).append(name)
    out: dict[str, str] = {}
    for site, names in per_source.items():
        rep = _majority(names)  # type: ignore[arg-type]
        if rep:
            out[site] = str(rep)
    return out


def _canonical_name(
    rooms: list[dict[str, Any]], source_names: dict[str, str]
) -> str | None:
    """canonical_name = 部屋数が最多のソースの代表名(同数は先着・§7)。"""
    room_counts: dict[str, int] = {}
    order: list[str] = []
    for r in rooms:
        site = r["source_site"]
        if site not in room_counts:
            order.append(site)
            room_counts[site] = 0
        room_counts[site] += 1
    best_site = max(order, key=lambda s: room_counts[s])
    return source_names.get(best_site)


def recompute_building(cur: psycopg.Cursor, building_id: int) -> None:
    """buildings 行を部屋行から再集約する(§7)。冪等。空 building は残す(§4)。"""
    rooms = [
        dict(r)
        for r in cur.execute(
            "SELECT * FROM properties WHERE building_id = %s ORDER BY id", (building_id,)
        )
    ]
    if not rooms:
        # 部屋 0 件(merge/split の残骸)は集約値をNULL化して保持。削除は運用しない
        cur.execute(
            """
            UPDATE buildings SET canonical_name = NULL, prefecture_slug = NULL,
                prefecture_name = NULL, municipality = NULL, address = NULL,
                lat = NULL, lng = NULL, geocode_source = NULL, geocode_confidence = NULL,
                built_year = NULL, structure = NULL, building_floors = NULL,
                is_active = FALSE, min_daily_rent_yen = NULL, min_plan_total_yen = NULL,
                units_count = 0, active_units_count = 0,
                last_seen_at = %s
            WHERE id = %s
            """,
            (_now(), building_id),
        )
        return

    active_rooms = [r for r in rooms if r.get("is_active")]
    source_names = _source_representative_names(rooms)
    canonical = _canonical_name(rooms, source_names)
    address = _majority([r.get("address") for r in rooms])
    rep_rooms = [r for r in rooms if r.get("address") == address] or rooms
    coords = _majority_coords(rooms)
    target_rooms = active_rooms or rooms
    min_daily, min_total = _min_rent_of_rooms(
        cur, [r["id"] for r in target_rooms]
    )
    first_seen = min(
        (r["first_seen_at"] for r in rooms if r.get("first_seen_at")), default=None
    )
    last_seen = max(
        (r["last_seen_at"] for r in rooms if r.get("last_seen_at")), default=None
    )

    cur.execute(
        """
        UPDATE buildings SET
            canonical_name = %s, prefecture_slug = %s, prefecture_name = %s,
            municipality = %s, address = %s,
            lat = %s, lng = %s, geocode_source = %s, geocode_confidence = %s,
            built_year = %s, structure = %s, building_floors = %s,
            is_active = %s, min_daily_rent_yen = %s, min_plan_total_yen = %s,
            units_count = %s, active_units_count = %s,
            first_seen_at = COALESCE(first_seen_at, %s), last_seen_at = %s
        WHERE id = %s
        """,
        (
            canonical,
            _majority([r.get("prefecture_slug") for r in rep_rooms]),
            _majority([r.get("prefecture_name") for r in rep_rooms]),
            _majority([r.get("municipality") for r in rep_rooms]),
            address,
            coords[0] if coords else None,
            coords[1] if coords else None,
            coords[2] if coords else None,
            coords[3] if coords else None,
            _majority([r.get("built_year") for r in rooms]),
            _majority([r.get("structure") for r in rooms]),
            _majority([r.get("building_floors") for r in rooms]),
            bool(active_rooms),
            min_daily,
            min_total,
            len(rooms),
            len(active_rooms),
            first_seen,
            last_seen,
            building_id,
        ),
    )

    # building_names: ソース代表名の登録(冪数・UNIQUE で重複無視)
    for site, name in source_names.items():
        cur.execute(
            """
            INSERT INTO building_names (building_id, source_site, name)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (building_id, site, name),
        )


# ----------------------------------------------------------------------
# 割当(スクレイプ時フック = §5 第 1 段)
# ----------------------------------------------------------------------


def assign_building(
    cur: psycopg.Cursor, property_id: int, *, recompute: bool = True
) -> int | None:
    """部屋 → 建物の決定的割当(address_key 完全一致のみ・§5).

    - address NULL は割当なし(NULL 許容が正設計・§4)
    - 住所変更(スクレイプで address が変わった)は自動で正しい建物へ移動
    - 割当後に建物の代表値を再集約(同一トランザクション)
    """
    row = cur.execute(
        "SELECT id, source_site, title, address, building_id FROM properties WHERE id = %s",
        (property_id,),
    ).fetchone()
    if row is None:
        return None

    key = normalize_address_key(row["address"])
    if key is None:
        if row["building_id"] is not None:
            cur.execute(
                "UPDATE properties SET building_id = NULL WHERE id = %s", (property_id,)
            )
        return None

    building_id: int | None
    existing = cur.execute(
        "SELECT id FROM buildings WHERE address_key = %s", (key,)
    ).fetchone()
    if existing is not None:
        building_id = int(existing["id"])
    else:
        cur.execute(
            "INSERT INTO buildings (address_key, first_seen_at, last_seen_at)"
            " VALUES (%s, %s, %s) RETURNING id",
            (key, _now(), _now()),
        )
        building_id = int(cur.fetchone()["id"])

    previous = row["building_id"]
    if previous != building_id:
        cur.execute(
            "UPDATE properties SET building_id = %s WHERE id = %s",
            (building_id, property_id),
        )
    name = extract_building_name(row["source_site"], row["title"])
    if name:
        cur.execute(
            """
            INSERT INTO building_names (building_id, source_site, name)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (building_id, row["source_site"], name),
        )
    if recompute:
        recompute_building(cur, building_id)
        if previous is not None and previous != building_id:
            recompute_building(cur, int(previous))
    return building_id


# ----------------------------------------------------------------------
# バッチ(日次 = §5 第 2 段)と dry-run レポート
# ----------------------------------------------------------------------


def _plan_assignments(cur: psycopg.Cursor) -> dict[str, Any]:
    """全部屋の割当計画を計算(dry-run と apply の共通核・書き込み無し)。"""
    rows = [
        dict(r)
        for r in cur.execute(
            "SELECT id, source_site, title, address, building_id, lat, lng,"
            " built_year, building_floors FROM properties"
        )
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    unassigned: list[dict[str, Any]] = []
    for r in rows:
        key = normalize_address_key(r["address"])
        if key is None:
            unassigned.append({"property_id": r["id"], "source_site": r["source_site"]})
            continue
        groups.setdefault(key, []).append(r)

    existing_keys = {
        row["address_key"]: int(row["id"])
        for row in cur.execute("SELECT id, address_key FROM buildings")
    }

    to_create: list[str] = [k for k in groups if k not in existing_keys]
    moves: list[dict[str, Any]] = []
    for key, members in groups.items():
        target = existing_keys.get(key)
        for m in members:
            if target is None:
                # 建物未作成の address_key: 全員が割当対象(to=None は
                # apply 時に assign_building が建物を作成して割り当てる)
                if m["building_id"] is not None:
                    # 既にどこかの建物に付いている場合は address_key 変化
                    moves.append(
                        {"property_id": m["id"], "from": m["building_id"], "to": None}
                    )
                else:
                    moves.append(
                        {"property_id": m["id"], "from": None, "to": None}
                    )
            elif m["building_id"] != target:
                moves.append(
                    {"property_id": m["id"], "from": m["building_id"], "to": target}
                )

    # コンフリクト検出(§5 検証信号)
    name_conflicts: list[dict[str, Any]] = []
    coord_conflicts: list[dict[str, Any]] = []
    attr_conflicts: list[dict[str, Any]] = []
    cross_source: list[dict[str, Any]] = []
    for key, members in groups.items():
        by_source: dict[str, set[str]] = {}
        for m in members:
            name = extract_building_name(m["source_site"], m["title"])
            if name:
                by_source.setdefault(m["source_site"], set()).add(name)
        multi = {s: sorted(n) for s, n in by_source.items() if len(n) > 1}
        if multi:
            name_conflicts.append(
                {
                    "address_key": key,
                    "address": members[0]["address"],
                    "rooms": len(members),
                    "names": multi,
                }
            )
        coords = {
            (m["lat"], m["lng"])
            for m in members
            if m.get("lat") is not None and m.get("lng") is not None
        }
        if len(coords) > 1:
            coord_conflicts.append(
                {
                    "address_key": key,
                    "address": members[0]["address"],
                    "rooms": len(members),
                    "distinct_coords": len(coords),
                }
            )
        for column in ("built_year", "building_floors"):
            vals = {m.get(column) for m in members if m.get(column) is not None}
            if len(vals) > 1:
                attr_conflicts.append(
                    {
                        "address_key": key,
                        "column": column,
                        "values": sorted(str(v) for v in vals),
                    }
                )
        sources = {m["source_site"] for m in members}
        if len(sources) > 1:
            cross_source.append(
                {
                    "address_key": key,
                    "address": members[0]["address"],
                    "sources": sorted(sources),
                    "rooms": len(members),
                }
            )

    return {
        "total_properties": len(rows),
        "grouped_properties": sum(len(m) for m in groups.values()),
        "building_groups": len(groups),
        "buildings_existing": len(existing_keys),
        "buildings_to_create": len(to_create),
        "moves": moves,
        "unassigned": unassigned,
        "name_conflicts": name_conflicts,
        "coord_conflicts": coord_conflicts,
        "attr_conflicts": attr_conflicts,
        "cross_source_buildings": cross_source,
    }


def run_identity_batch(conn: psycopg.Connection, *, apply: bool = False) -> dict[str, Any]:
    """名寄せバッチ(§5 第 2 段)。apply=False は dry-run(書き込みゼロ)。"""
    cur = conn.cursor()
    plan = _plan_assignments(cur)
    report: dict[str, Any] = dict(plan)
    report["apply"] = apply

    # 建物ショートリスト保持建物の影響透明性(部屋の引越しで saved 建物の
    # 所属部屋が減る可能性の通知・バッチ自体は建物行を削除しないため状態は不変)
    if _building_shortlists_exists(cur):
        report["building_shortlists_rows"] = int(
            cur.execute("SELECT COUNT(*) FROM building_shortlists").fetchone()[0]
        )

    if apply:
        # 割当は assign_building の決定的経路を部屋ごとに適用(冪等。
        # 8k 件規模で十分に速く、upsert フックと完全に同一の経路になる)
        for move in plan["moves"]:
            assign_building(cur, move["property_id"], recompute=False)
        # 建物代表値を一括再集約(moves で触った建物 + 新規作成分)
        dirty: set[int] = set()
        for move in plan["moves"]:
            if move.get("to") is not None:
                dirty.add(int(move["to"]))
            if move.get("from") is not None:
                dirty.add(int(move["from"]))
        for move in plan["moves"]:
            if move.get("to") is None:
                row = cur.execute(
                    "SELECT building_id FROM properties WHERE id = %s",
                    (move["property_id"],),
                ).fetchone()
                if row and row["building_id"] is not None:
                    dirty.add(int(row["building_id"]))
        for row in cur.execute("SELECT id FROM buildings").fetchall():
            bid = int(row["id"])
            if bid not in dirty:
                recompute_building(cur, bid)
        for bid in sorted(dirty):
            recompute_building(cur, bid)
        # 空建物(所属部屋 0)の掃除: 住所変更・正規化変更で部屋が移り済んだ
        # 旧キー建物が残るため。検索・GeoJSON には出ないが蓄積するので削除する
        # (building_names は FK ON DELETE CASCADE で同時に消える)
        cur.execute(
            "DELETE FROM buildings WHERE id NOT IN"
            " (SELECT DISTINCT building_id FROM properties WHERE building_id IS NOT NULL)"
        )
        report["buildings_removed_empty"] = cur.rowcount if cur.rowcount >= 0 else 0
        conn.commit()
        # 適用後の状態でサマリを更新
        after = cur.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
        assigned = cur.execute(
            "SELECT COUNT(*) FROM properties WHERE building_id IS NOT NULL"
        ).fetchone()[0]
        report["buildings_after"] = int(after)
        report["assigned_properties"] = int(assigned)
    return report


# ----------------------------------------------------------------------
# 手動オーバーライド CLI(building-merge / building-split)
# ----------------------------------------------------------------------


def _building_shortlists_exists(cur: psycopg.Cursor) -> bool:
    """building_shortlists テーブルの存在確認(v5 未適用 DB での安全弁)。"""
    return bool(
        cur.execute(
            "SELECT to_regclass('public.building_shortlists') IS NOT NULL AS table_exists"
        ).fetchone()["table_exists"]
    )


def _carry_building_shortlist(
    cur: psycopg.Cursor, building_id_a: int, building_id_b: int
) -> None:
    """統合される建物 b のショートリスト状態を残存建物 a へ移行.

    両方に行がある場合は updated_at が新しい方の status を採用し、comment は
    非_null 優先(両方あれば改行連結)。b の行は削除(buildings 行 DELETE の
    CASCADE で黙って消えないよう、明示的に先に移行する)。
    """
    if not _building_shortlists_exists(cur):
        return
    b_sl = cur.execute(
        "SELECT status, comment, updated_at FROM building_shortlists WHERE building_id = %s",
        (building_id_b,),
    ).fetchone()
    if b_sl is None:
        return
    a_sl = cur.execute(
        "SELECT status, comment, updated_at FROM building_shortlists WHERE building_id = %s",
        (building_id_a,),
    ).fetchone()
    if a_sl is None:
        cur.execute(
            "UPDATE building_shortlists SET building_id = %s WHERE building_id = %s",
            (building_id_a, building_id_b),
        )
        return
    # updated_at は timestamptz (Phase 6c) の datetime が返るため直接比較
    # (テストの直 INSERT 由来の str とも混在しない — merge 経路は DB 行のみ)
    _ua, _ub = a_sl["updated_at"], b_sl["updated_at"]
    winner = b_sl if (_ub is not None and (_ua is None or _ub > _ua)) else a_sl
    comments = [c for c in (a_sl["comment"], b_sl["comment"]) if c]
    cur.execute(
        """
        UPDATE building_shortlists
        SET status = %s, comment = %s, updated_at = %s
        WHERE building_id = %s
        """,
        (
            winner["status"],
            "\n".join(comments) if comments else None,
            winner["updated_at"],
            building_id_a,
        ),
    )
    cur.execute(
        "DELETE FROM building_shortlists WHERE building_id = %s", (building_id_b,)
    )


def merge_buildings(
    conn: psycopg.Connection, building_id_a: int, building_id_b: int
) -> int:
    """b を a へ統合(部屋の building_id 貼替え + b 削除)。代表値は再計算。"""
    if building_id_a == building_id_b:
        raise ValueError("同一 building_id は統合できません")
    cur = conn.cursor()
    if not cur.execute("SELECT 1 FROM buildings WHERE id = %s", (building_id_a,)).fetchone():
        raise ValueError(f"building {building_id_a} が存在しません")
    if not cur.execute("SELECT 1 FROM buildings WHERE id = %s", (building_id_b,)).fetchone():
        raise ValueError(f"building {building_id_b} が存在しません")
    cur.execute(
        "UPDATE properties SET building_id = %s WHERE building_id = %s",
        (building_id_a, building_id_b),
    )
    # 建物ショートリスト状態を b → a へ移行(b の CASCADE 削除で失わせない)
    _carry_building_shortlist(cur, building_id_a, building_id_b)
    # address_key は a のまま(b の別キーを取り込む=手動マージの意思)
    cur.execute("DELETE FROM buildings WHERE id = %s", (building_id_b,))
    recompute_building(cur, building_id_a)
    conn.commit()
    moved = cur.execute(
        "SELECT COUNT(*) FROM properties WHERE building_id = %s", (building_id_a,)
    ).fetchone()[0]
    return int(moved)


def split_building(
    conn: psycopg.Connection,
    building_id: int,
    property_ids: list[int],
) -> int:
    """指定部屋を別建物へ分割(同一住所 2 棟等の手動対処・§10)。

    新建物の address_key は元キー + "#splitN"(手動分割であることをキーで識別可能)。
    建物ショートリスト状態は元建物側に保持する(移った部屋の個別状態は
    部屋単位の property_shortlists が追従するため二重管理にならない)。
    """
    if not property_ids:
        raise ValueError("移動する property_id を指定してください")
    cur = conn.cursor()
    base = cur.execute(
        "SELECT address_key FROM buildings WHERE id = %s", (building_id,)
    ).fetchone()
    if base is None:
        raise ValueError(f"building {building_id} が存在しません")
    base_key = base["address_key"]
    n = 1
    while cur.execute(
        "SELECT 1 FROM buildings WHERE address_key = %s", (f"{base_key}#split{n}",)
    ).fetchone():
        n += 1
    cur.execute(
        "INSERT INTO buildings (address_key, first_seen_at, last_seen_at)"
        " VALUES (%s, %s, %s) RETURNING id",
        (f"{base_key}#split{n}", _now(), _now()),
    )
    new_id = int(cur.fetchone()["id"])
    ph = ",".join("%s" for _ in property_ids)
    cur.execute(
        f"UPDATE properties SET building_id = %s WHERE id IN ({ph}) AND building_id = %s",
        (new_id, *property_ids, building_id),
    )
    recompute_building(cur, building_id)
    recompute_building(cur, new_id)
    conn.commit()
    return new_id
