"""web 層パッケージ: FastAPI アプリの組立と配信。

- app.py:           create_app() + lifespan + tiles / StaticFiles 登録
- tasks.py:         バックグラウンドタスクランナ (TASK_STATUS 共有)
- rotation_jobs.py: 県ローテーションのスケジュール / ポリシ解決
- routers/:         領域別ルータ (FE frontend/src/lib/api/ の粒度と 1:1 対応)

互換入口は src/web_server.py シム (Docker CMD / tests / export_openapi が
`web_server:app` を参照し続けられる)。
"""

import os

# リポジトリルート (src/web/ から 3 層上)。frontend/dist 等の解決に使用
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
