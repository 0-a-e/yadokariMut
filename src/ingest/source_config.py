"""スクレイプ実行時のアダプタ設定組立 (CLI / Web runner 共通の唯一の窓口).

優先順位: run時明示 delay > DB保存値 (scrape_settings) > config.json
sources.<id> > コード既定。旧 cli.py の config.json 直読みと
web/tasks.py の組立処理を統合し、CLI / Web で実効パラメタが拗れないようにする。
"""

from __future__ import annotations

from typing import Any, Optional


def resolve_source_adapter_config(
    source_id: str,
    *,
    pref_filter: Optional[list[str]] = None,
    delay: Optional[float] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """ソース1件分のアダプタ設定を実効値として解決する.

    config には load_app_config() の結果を渡せる(複数ソース実行時の再読込回避)。
    未指定なら関数内で読む。
    """
    from scrape_settings import apply_to_source_config
    from store.source_catalog import load_app_config

    cfg = dict(((config or load_app_config()).get("sources") or {}).get(source_id) or {})
    if pref_filter:
        cfg["pref_filter"] = pref_filter
    # DB保存のソース別上書き(取得間隔/制限時クールダウン)を適用。
    # run時の明示指定(delay)がさらに優先
    cfg = apply_to_source_config(source_id, cfg)
    if delay is not None:
        cfg["delay_seconds"] = delay
    return cfg
