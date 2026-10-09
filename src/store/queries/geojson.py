"""建物単位 GeoJSON エクスポート(B2-ε: 部屋単位経路を廃止).

旧部屋単位の _geojson_feature_from_prop / iter_geojson_features / export_geojson は
B2-ε で削除(docs/building-aggregation-design.md §6.1 — FE は /api/buildings/geojson
へ移行済み・soak 完了後に廃止)。配信エンドポイントは routers/buildings_geojson.py、
ストリームの実体は queries.buildings.iter_geojson_building_features。
"""

from __future__ import annotations

import os
from typing import Any

from store.queries.buildings import iter_geojson_building_features


def _write_geojson_document(
    geojson: dict[str, Any], file_path: str | None
) -> dict[str, Any]:
    """FeatureCollection dict をファイルへ書き出し、応答辞書を返す."""
    import json

    if file_path is None:
        # 既定出力先はリポジトリルート直下ではなく data/exports/ (永続領域・デプロイ同期外)
        # 本ファイルは src/store/queries/ 配下のためルートへは 3 つ上へ辿る
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "data",
            "exports",
            "map.geojson",
        )
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    return {"status": "success", "file_path": file_path, "feature_count": len(geojson["features"])}


def export_building_geojson(
    params: dict[str, Any] | None = None, file_path: str | None = None
) -> dict[str, Any]:
    """建物単位 GeoJSON エクスポート (MCP export_geojson / CLI export-map の実体・設計 §6.2).

    /api/buildings/geojson と同一ビルダー (iter_geojson_building_features) で
    1 Feature = 1 建物 + units 配列 (全部屋搭載) を書き出す。
    feature_count の単位は建物数。limit の既定は 10000 (建物数単位)。
    """
    export_params = dict(params or {})
    export_params.setdefault("limit", 10000)
    features = list(iter_geojson_building_features(export_params))
    return _write_geojson_document(
        {"type": "FeatureCollection", "features": features}, file_path
    )
