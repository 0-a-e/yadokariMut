"""互換シム: 旧 web_server 単一モジュール → web パッケージの入口。

実体は src/web/ へ分割済み (app.py = create_app / tasks.py = バックグラウンド
タスク / rotation_jobs.py = ローテーション設定解決 / routers/ = 領域別)。
Docker CMD (`uvicorn web_server:app`)・tests・scripts/export_openapi が
`web_server` フラット名を参照し続けられるよう、ここから**同一オブジェクト**を
再輸出する。再代入で別オブジェクトにすると TASK_STATUS 等の状態共有が壊れる。
"""

from web.app import app  # noqa: F401
from web.routers.geojson import get_geojson_data  # noqa: F401
from web.rotation_jobs import (  # noqa: F401
    _rotation_failure_policy,
    _rotation_pref_catalog,
    _rotation_queue_key,
    _rotation_source_config,
)
from web.tasks import (  # noqa: F401
    TASK_STATUS,
    log_task,
    run_geocode_task,
    run_rotation_job,
    run_scrape_task,
)
