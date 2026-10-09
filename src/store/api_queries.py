"""Back-compat shim: 実装本体は store.queries パッケージへ分割済み.

store.api_queries を import する既存呼び出し側 (web_server / mcp_server / cli /
tests) を無変更で維持するための再輸出レイヤ。旧モジュールが公開していた名前
(内部ヘルパ含む) はすべて store.queries 配下の各モジュールに移設済みで、
シグネチャ・挙動・応答契約は変更していない。新規コードは store.queries 配下の
各モジュールを直接 import すること。
"""

from store.queries import (  # noqa: F401
    SOURCE_DISPLAY,
    AmbiguousPropertyLookup,
    _CARRY_FORWARD_WINDOW_DAYS,
    _CHILD_IN_CHUNK,
    _TREND_CARRIED_SQL,
    _TREND_CHG_SQL,
    _TREND_DAILY_CTES,
    _fetch_child_rows_by_property,
    _guard_price_history,
    _hist_median_avg,
    _property_row_to_result,
    _repo,
    _search_where,
    _trend_ctes,
    apply_effective_rent_plans,
    clean_point_text,
    compare_properties,
    export_kml,
    get_price_trend,
    get_properties_by_ids,
    get_property_detail,
    iter_search_properties,
    price_plan_row_to_rent_plan,
    resolve_property_id,
    search_properties,
    update_shortlist,
    update_building_shortlist,
)
