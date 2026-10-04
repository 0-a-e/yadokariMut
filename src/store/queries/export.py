"""KML エクスポート."""

from __future__ import annotations

import os
from typing import Any

from store.kml_export import build_kml_document
from store.queries.search import search_properties


def export_kml(params: dict[str, Any] | None = None, file_path: str | None = None) -> dict[str, Any]:
    """(MCP/CLI用) 検索条件に一致する物件を KML ファイルへ書き出す.

    KML 文字列の生成は store.kml_export.build_kml_document に一任する。
    """
    export_params = dict(params) if params else {}
    if "limit" not in export_params:
        export_params["limit"] = 10000
    properties = search_properties(export_params)
    kml_str = build_kml_document(properties)

    if not file_path:
        # 既定出力先はリポジトリルート直下ではなく data/exports/ (永続領域・デプロイ同期外)
        # 本ファイルは src/store/queries/ 配下のためルートへは 3 つ上へ辿る
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "data",
            "exports",
            "map.kml",
        )
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(kml_str)

    mappable = sum(
        1 for p in properties if p.get("lat") is not None and p.get("lng") is not None
    )
    return {"status": "success", "file_path": file_path, "placemark_count": mappable}
