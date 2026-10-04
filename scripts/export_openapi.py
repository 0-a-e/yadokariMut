"""FastAPI アプリの OpenAPI スキーマを frontend/openapi.json へ書き出す。

契約正本は src/api_models.py (pydantic v2) を response_model に接続した
web_server.app。FE はこの JSON を openapi-typescript で src/lib/api/schema.d.ts
に変換して型として取り込む(frontend/package.json の generate:api)。

実行(リポジトリルートで):
    python3 -m scripts.export_openapi

.env は web_server.py 側の module-level load_dotenv() で読まれるため、
本スクリプトは読み込みを行わない。サーバ起動は不要(import のみ)。
"""

import json
import os
import sys

# リポジトリルートからの相対で src/ を import 可能にする
# (python -m scripts.export_openapi 実行時のカレントを想定)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

OUTPUT_PATH = os.path.join(REPO_ROOT, "frontend", "openapi.json")


def main() -> None:
    from web_server import app

    schema = app.openapi()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"OpenAPI schema written to {os.path.relpath(OUTPUT_PATH, REPO_ROOT)}")


if __name__ == "__main__":
    main()
