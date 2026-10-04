"""v2 スキーマの読み出し系クエリパッケージ (旧 store.api_queries の分割体).

SQL 結果を api_models の応答契約互換 dict へ変換する「変換レイヤ」で、
構成は次のとおり:

- ``_common``      : 接続取得 / 物件 id 解決 / 行→契約モデル変換の共用部品
- ``search``       : 検索 / 件数 / PK 一括取得
- ``detail``       : 物件詳細 / 比較 / ショートリスト更新
- ``price_history``: 価格履歴ガード / 価格変動トレンド
- ``geojson``      : GeoJSON Feature 組み立て / ストリーム / 一括エクスポート
- ``export``       : KML エクスポート

旧 store.api_queries が公開していた名前はすべて本パッケージから再輸出する
(store.api_queries は互換シム)。表示名 SSOT は store.source_catalog.SOURCE_DISPLAY
で、依存方向は queries → source_catalog の一方向。
"""

from store.queries._common import (
    SOURCE_DISPLAY,
    AmbiguousPropertyLookup,
    _CHILD_IN_CHUNK,
    _fetch_child_rows_by_property,
    _property_row_to_result,
    _repo,
    apply_effective_rent_plans,
    clean_point_text,
    price_plan_row_to_rent_plan,
    resolve_property_id,
)
from store.queries.detail import (
    compare_properties,
    get_property_detail,
    update_shortlist,
)
from store.queries.export import export_kml
from store.queries.geojson import (
    _geojson_feature_from_prop,
    export_geojson,
    iter_geojson_features,
)
from store.queries.price_history import (
    _CARRY_FORWARD_WINDOW_DAYS,
    _TREND_CARRIED_SQL,
    _TREND_CHG_SQL,
    _TREND_DAILY_CTES,
    _guard_price_history,
    _hist_median_avg,
    _trend_ctes,
    get_price_trend,
)
from store.queries.search import (
    _search_where,
    count_properties,
    get_properties_by_ids,
    iter_search_properties,
    search_properties,
)

__all__ = [
    "SOURCE_DISPLAY",
    "AmbiguousPropertyLookup",
    "resolve_property_id",
    "price_plan_row_to_rent_plan",
    "apply_effective_rent_plans",
    "clean_point_text",
    "iter_search_properties",
    "search_properties",
    "count_properties",
    "get_properties_by_ids",
    "get_property_detail",
    "compare_properties",
    "update_shortlist",
    "get_price_trend",
    "iter_geojson_features",
    "export_geojson",
    "export_kml",
]
