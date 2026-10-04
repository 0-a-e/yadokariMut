#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAPI 応答契約と FE 生成型 (schema.d.ts) の同期を検証するテスト.

BE 契約を変えた後に schema.d.ts の再生成を忘れることを防ぐため、
3 段階で検証する:

1. OpenAPI 生成可能か: app.openapi() がエラー無く生成でき、
   除外対象外の全エンドポイントの 200 応答が $ref (response_model 由来)
   を持つこと(response_model 未指定のエンドポイントの混入を検出)。
2. 生成型との名前整合: schema.d.ts の components.schemas のモデル名と
   app.openapi() の components.schemas のキーセットが過不足なく一致すること。
3. フル同期検証: openapi-typescript を subprocess で実行し、新規生成物と
   コミット済み schema.d.ts が byte 同値であること。
   node / pnpm / frontend/node_modules が無い環境では skip する
   (公開リポジトリや CI 最小環境での誤失敗を防ぐ)。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from web_server import app

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DTS_PATH = REPO_ROOT / "frontend" / "src" / "lib" / "api" / "schema.d.ts"

# 200 応答が $ref を持たないことが既知のエンドポイント(Response 系・行契約)。
# 新たに response_model を持てる JSON API を足した場合はここに載せず型付けること。
UNTYPED_EXEMPT_PATHS: set[str] = {
    "/",  # FileResponse (index.html) / StaticFiles マウント
    "/api/copilotkit",  # AG-UI の StreamingResponse (SSE 行契約)
    "/api/geojson/stream",  # NDJSON StreamingResponse (行契約)
    "/api/export/kml",  # KML ファイルダウンロード (Response 系)
}
UNTYPED_EXEMPT_PATH_PREFIXES = (
    "/api/tiles/",  # PMTiles/MVT バイナリ配信 (Response 系)
)

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

# openapi-typescript v7 の生成形式:
#   export interface components { schemas: { ModelName: {...}; ... } ... }
_DTS_COMPONENTS_RE = re.compile(r"^export interface components \{", re.MULTILINE)
_DTS_SCHEMA_KEY_RE = re.compile(r"^        ([A-Za-z_$][\w$]*):")


def _contains_ref(node: object) -> bool:
    """スキーマ断片のどこかに $ref を含むか(FastAPI は components 参照を出す)."""
    if isinstance(node, dict):
        return "$ref" in node or any(_contains_ref(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_ref(v) for v in node)
    return False


def _extract_dts_schema_names(text: str) -> set[str]:
    """schema.d.ts の components.schemas 直下のモデル名を正規表現パースで抽出する."""
    m = _DTS_COMPONENTS_RE.search(text)
    if m is None:
        raise AssertionError(
            "schema.d.ts に 'export interface components {' が見つかりません"
            "(openapi-typescript v7 の生成形式を想定しています)"
        )
    names: set[str] = set()
    in_schemas = False
    depth = 0
    for line in text[m.end() :].splitlines():
        stripped = line.strip()
        if not in_schemas:
            # schemas: never; (モデルゼロ) の場合も文法上あり得る
            if re.match(r"^schemas:\s*never\b", stripped):
                return set()
            if re.match(r"^schemas:\s*\{", stripped):
                in_schemas = True
                depth = 1
            continue
        # JSDoc コメント行は括弧の対応計算に影響させない
        if stripped.startswith(("/*", "*", "*/")):
            continue
        if depth == 1:
            key = _DTS_SCHEMA_KEY_RE.match(line)
            if key:
                names.add(key.group(1))
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break  # schemas ブロックの閉じで終了
    return names


# ============================================================
# 段階 1: OpenAPI 生成可能性 + 全エンドポイントの 200 応答が $ref 持ち
# ============================================================
def test_openapi_generates_and_all_responses_are_typed():
    schema = app.openapi()  # 生成自体がエラー無くできること
    assert schema.get("openapi"), "OpenAPI スキーマが生成できていない"

    paths = schema.get("paths") or {}
    assert paths, "エンドポイントが 1 つも検出されない"

    violations: list[str] = []
    for path, ops in paths.items():
        if path in UNTYPED_EXEMPT_PATHS or path.startswith(UNTYPED_EXEMPT_PATH_PREFIXES):
            continue
        for method, op in ops.items():
            if method not in _HTTP_METHODS:
                continue
            operation_id = op.get("operationId") or f"{method.upper()} {path}"
            responses = op.get("responses") or {}
            response_200 = responses.get("200")
            if response_200 is None:
                violations.append(f"{operation_id}: 200 応答が未定義")
                continue
            content = response_200.get("content") or {}
            if not content:
                violations.append(f"{operation_id}: 200 応答に content が無い")
                continue
            for media_type, media in content.items():
                if not _contains_ref(media.get("schema")):
                    violations.append(
                        f"{operation_id}: 200 応答 ({media_type}) が $ref を持たない"
                        "(response_model 未指定の可能性)"
                    )
    assert not violations, (
        "response_model 未接続のエンドポイントを検出しました:\n  " + "\n  ".join(violations)
    )


# ============================================================
# 段階 2: schema.d.ts のモデル名と app.openapi() の schemas の過不足ゼロ
# ============================================================
def test_schema_dts_model_names_match_openapi_components():
    be_names = set((app.openapi().get("components") or {}).get("schemas") or {})
    assert be_names, "components.schemas が空(pydantic モデルが 1 つも参照されていない)"

    dts_names = _extract_dts_schema_names(SCHEMA_DTS_PATH.read_text(encoding="utf-8"))

    missing = sorted(be_names - dts_names)  # BE にあるのに d.ts に無い(再生成忘れ)
    extra = sorted(dts_names - be_names)  # d.ts にだけ残る(削除後の再生成忘れ)
    assert not missing and not extra, (
        f"schema.d.ts と OpenAPI components.schemas のモデル名が不一致です。"
        f"再生成してください (cd frontend && pnpm generate:api)\n"
        f"  d.ts に無い (BE で追加): {missing}\n"
        f"  d.ts にだけある (BE で削除済み): {extra}"
    )


# ============================================================
# 段階 3: openapi-typescript の新規生成物とコミット済み d.ts が byte 同値
# ============================================================
def _frontend_toolchain_skip_reason() -> str | None:
    """段階 3 を実行できない環境なら skip 理由を返す."""
    if shutil.which("node") is None:
        return "node が無いためスキップ"
    if shutil.which("pnpm") is None:
        return "pnpm が無いためスキップ"
    node_modules = REPO_ROOT / "frontend" / "node_modules"
    if not node_modules.is_dir():
        return "frontend/node_modules が無いためスキップ (pnpm install で検証可能)"
    if not (node_modules / "openapi-typescript").is_dir():
        return "openapi-typescript が未インストールのためスキップ"
    return None


def test_schema_dts_matches_fresh_codegen():
    skip_reason = _frontend_toolchain_skip_reason()
    if skip_reason:
        pytest.skip(skip_reason)

    # scripts.export_openapi 相当: app.openapi() から直接 JSON を書き出す
    schema = app.openapi()
    with tempfile.TemporaryDirectory(prefix="api-contract-sync-") as tmp:
        input_path = Path(tmp) / "openapi.json"
        input_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        output_path = Path(tmp) / "schema.d.ts"
        proc = subprocess.run(
            ["pnpm", "exec", "openapi-typescript", str(input_path), "-o", str(output_path)],
            cwd=REPO_ROOT / "frontend",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, (
            f"openapi-typescript の実行に失敗: stderr=\n{proc.stderr[-2000:]}"
        )
        committed = SCHEMA_DTS_PATH.read_bytes()
        fresh = output_path.read_bytes()
        assert fresh == committed, (
            "openapi-typescript の生成物とコミット済み schema.d.ts が一致しません。"
            "BE 契約変更後に再生成を忘れています (cd frontend && pnpm generate:api)"
        )
