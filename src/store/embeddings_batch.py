"""embedding 生成の Gemini Batch API 経路 (``asyncBatchEmbedContent``)。

docs/embedding-batch-api-plan.md (2026-10-09 承認・D1-D5):

- **Bulk 経路 (CLI ``backfill-embeddings`` 既定 + 日次ジョブ) は本モジュールに
  一本化**。シリアル 1 件 1 呼びの sync 経路
  (:func:`store.embeddings.backfill_embeddings`) はレート制限 (本番 403 実績) に
  接触するため小件フォールバック (``--mode sync``) に退く。
- Batch API は標準料金の 50%・24h SLO (実測では小ジョブ数分)・バッチ専用枠で
  インタラクティブ枠のレート制限に接触しない。
- 入力は **JSONL ファイル 1 本** (inline 入力は使わない — 応答の所在が入力方式で
  切り替わるためコードパスを 1 本化する)。1 行::

      {"request": {"content": {"parts": [{"text": ...}]},
                   "embedContentConfig": {"outputDimensionality": 3072}},
       "metadata": {"key": "<property_id>", "hash": "<submit 時 hash>"}}

  ``metadata`` は応答へ完全に往復する (実キー検証済み) ので、API 側の順序に
  依存せず property_id と submit 時 hash を紐付けられる。
- **stale guard**: 適用時、現在の ``compose_texts_for`` 結果の hash が submit 時
  hash と一致した場合のみ upsert する。submit→適用の間に部屋内容が変わっていた
  場合はスキップし次サイクルで自然に再対象 (sync 経路にはない間隔のギャップを
  構造的に遮断する)。
- **bookkeeping は ``app_settings``** (key=``embedding_batch_jobs``・D2): ジョブ毎に
  ``{name, display_name, request_count, pids, submitted_at, state}`` を保持する。
  状態の正本は Gemini 側 (``GET /v1beta/{name}``) で local は発見用インデックス
  のみ。``JsonSettingsStore`` (patch マージ系) は ledger の置換更新と非整合なため
  使わず直接 SQL とする。``pids`` は **未完了ジョブの二重 submit 防止**に使う
  (日跨ぎでジョブが未完了でも同じ物件を翌日の submit に含めない)。
- ジョブ作成は API 側で非冪等だが、適用側 (upsert) が冪等なので
  「FAILED/EXPIRED ジョブは破棄 → 対象物件は次サイクルで自然に再 submit」で安全。
- 404 (ジョブ消失)・FAILED/CANCELLED/EXPIRED はジョブを簿記から落として続行。

テストは session DI 点 (requests モジュール互換の ``post``/``get`` を持つ fake)
で実 API を呼ばない。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Iterable, Iterator

import psycopg
import requests

from store.embeddings import (
    EMBEDDING_API_ENV,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    GeminiEmbeddingError,
    compose_texts_for,
    upsert_embedding,
    visible_property_ids,
)
from store.pg import open_connection

_BATCH_API_BASE = "https://generativelanguage.googleapis.com"
_BATCH_CREATE_URL = (
    f"{_BATCH_API_BASE}/v1beta/models/{EMBEDDING_MODEL}:asyncBatchEmbedContent"
)
_BATCH_GET_URL = f"{_BATCH_API_BASE}/v1beta"
_FILES_UPLOAD_URL = f"{_BATCH_API_BASE}/upload/v1beta/files"
_FILE_DOWNLOAD_URL = f"{_BATCH_API_BASE}/download/v1beta"

# bookkeeping (D2)。値は {"jobs": [job, ...]} の 1 キー 1 行 JSON。
_JOBS_SETTINGS_KEY = "embedding_batch_jobs"

# displayName 規約 (GET /v1beta/batches 一覧との照合補助)。
_DISPLAY_PREFIX = "emb-"

_STATE_SUCCEEDED = "BATCH_STATE_SUCCEEDED"
_TERMINAL_STATES = {
    _STATE_SUCCEEDED,
    "BATCH_STATE_FAILED",
    "BATCH_STATE_CANCELLED",
    "BATCH_STATE_EXPIRED",
}

_TIMEOUT_S = 120  # upload / download は大容量 (数 MB〜数百 MB)
_RETRY_ATTEMPTS = 4

# bounded 待機のポーリング間隔と既定のジョブ分割幅 (D4)。
_POLL_INTERVAL_S = 30
_MAX_REQUESTS_PER_BATCH = 5000

# 適用 (compose → stale 判定 → upsert) のウィンドウ幅 (500 件進捗粒度の慣習)。
_APPLY_WINDOW = 500


class BatchJobNotFoundError(GeminiEmbeddingError):
    """``GET /v1beta/{name}`` が 404 (ジョブが API 側に存在しない)。"""


def build_input_jsonl(items: Iterable[tuple[int, str, str]]) -> bytes:
    """``[(property_id, text, hash)]`` をバッチ入力 JSONL bytes へ変換する。

    1 行 = 1 EmbedContentRequest。``taskType`` は embedding-2 で no-op なので
    送らない (非対称指示は ``text`` への接頭辞 = ``DOCUMENT_PREFIX`` 済み)。
    """
    lines = [
        json.dumps(
            {
                "request": {
                    "content": {"parts": [{"text": text}]},
                    "embedContentConfig": {"outputDimensionality": EMBEDDING_DIM},
                },
                "metadata": {"key": str(pid), "hash": digest},
            },
            ensure_ascii=False,
        )
        for pid, text, digest in items
    ]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


class GeminiEmbeddingBatchClient:
    """Batch API クライアント (requests 直叩き・session DI 点は sync と同型)。

    - ``session`` は requests モジュール互換 (``post`` / ``get`` を持つ)。
    - 429/5xx (とネットワーク断) は指数バックオフ 1s/2s/4s・3 回再試行。
      4xx は即時失敗 (404 のみ :class:`BatchJobNotFoundError`)。
    """

    def __init__(self, api_key: str | None = None, session: Any = None):
        key = api_key if api_key is not None else os.environ.get(EMBEDDING_API_ENV)
        if not key:
            raise GeminiEmbeddingError(
                f"環境変数 {EMBEDDING_API_ENV} が未設定です (Gemini Batch API に必須)。"
            )
        self._api_key = key
        self._session: Any = session if session is not None else requests

    # ------------------------------------------------------------------
    # HTTP 基盤
    # ------------------------------------------------------------------
    def _post(
        self,
        url: str,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = _TIMEOUT_S,
    ) -> Any:
        return self._send(
            lambda: self._session.post(
                url, json=json_body, data=data, headers=headers, timeout=timeout
            ),
            url,
        )

    def _get(self, url: str, *, timeout: int = _TIMEOUT_S) -> Any:
        return self._send(lambda: self._session.get(url, headers=self._headers(), timeout=timeout), url)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key}

    def _send(self, call: Any, url: str) -> Any:
        last_err: Exception | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                resp = call()
            except requests.RequestException as e:  # ネットワーク断も一時障害として再試行
                last_err = e
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code == 404:
                    raise BatchJobNotFoundError(f"Batch API 404 (job not found): {url}")
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = GeminiEmbeddingError(
                        f"Batch API {resp.status_code}: {str(resp.text)[:200]}"
                    )
                else:  # 4xx は再試行しても変わらないため即失敗
                    raise GeminiEmbeddingError(
                        f"Batch API failed {resp.status_code}: {str(resp.text)[:200]}"
                    )
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(2**attempt)  # 1s / 2s / 4s
        raise GeminiEmbeddingError(
            f"Batch API failed after {_RETRY_ATTEMPTS} attempts: {last_err}"
        ) from last_err

    # ------------------------------------------------------------------
    # 各ステップ
    # ------------------------------------------------------------------
    def upload_input_file(self, data: bytes, display_name: str) -> str:
        """Files API へ resumable 2 段で JSONL をアップロードし ``files/xxx`` を返す。"""
        start = self._post(
            _FILES_UPLOAD_URL,
            json_body={"file": {"display_name": display_name}},
            headers={
                **self._headers(),
                "Content-Type": "application/json",
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(data)),
                "X-Goog-Upload-Header-Content-Type": "jsonl",
            },
        )
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise GeminiEmbeddingError(
                f"Files upload: missing x-goog-upload-url: {str(start.text)[:200]}"
            )
        finalize = self._post(
            upload_url,
            data=data,
            headers={
                **self._headers(),
                "Content-Length": str(len(data)),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
                "Content-Type": "jsonl",
            },
        )
        try:
            name = finalize.json()["file"]["name"]
        except (KeyError, TypeError, ValueError) as e:
            raise GeminiEmbeddingError(
                f"Files upload: unexpected response: {str(finalize.text)[:200]}"
            ) from e
        if not isinstance(name, str) or not name.startswith("files/"):
            raise GeminiEmbeddingError(f"Files upload: unexpected file name: {name!r}")
        return name

    def create_batch(self, file_name: str, display_name: str) -> str:
        """ファイル入力の埋め込みバッチを作成し ``batches/xxx`` を返す。

        作成は API 側で非冪等 (同一内容の二重送信は 2 ジョブになる)。呼び出し側
        (:func:`run_batch_sync`) は簿記へ記録して二重送信を避ける。
        """
        resp = self._post(
            _BATCH_CREATE_URL,
            json_body={
                "batch": {
                    "displayName": display_name,
                    "inputConfig": {"fileName": file_name},
                }
            },
            headers=self._headers(),
        )
        try:
            name = resp.json()["name"]
        except (KeyError, TypeError, ValueError) as e:
            raise GeminiEmbeddingError(
                f"batch create: unexpected response: {str(resp.text)[:200]}"
            ) from e
        if not isinstance(name, str) or not name.startswith("batches/"):
            raise GeminiEmbeddingError(f"batch create: unexpected job name: {name!r}")
        return name

    def get_batch(self, name: str) -> dict:
        """ジョブ状態を取得する (Operation の metadata を平坦化)。

        戻り値: ``{"state", "stats", "output", "error"}``。
        """
        resp = self._get(f"{_BATCH_GET_URL}/{name}")
        try:
            body = resp.json()
        except (TypeError, ValueError) as e:
            raise GeminiEmbeddingError(
                f"batch get: unexpected response: {str(resp.text)[:200]}"
            ) from e
        meta = body.get("metadata") if isinstance(body, dict) else None
        data = meta if isinstance(meta, dict) and "state" in meta else body
        return {
            "state": data.get("state") if isinstance(data, dict) else None,
            "stats": (data.get("batchStats") or {}) if isinstance(data, dict) else {},
            "output": (data.get("output") or {}) if isinstance(data, dict) else {},
            "error": (body.get("error") if isinstance(body, dict) else None)
            or (data.get("error") if isinstance(data, dict) else None),
        }

    def iter_results(self, output: dict) -> Iterator[dict]:
        """完了ジョブの ``output`` から結果行 (``{metadata, response|error}``) を返す。

        ファイル入力ジョブは ``responsesFile`` (files/batch-*) だが、念のため
        inline 応答 (``inlinedResponses``) も支持する。
        """
        responses_file = output.get("responsesFile")
        if responses_file:
            resp = self._get(f"{_FILE_DOWNLOAD_URL}/{responses_file}:download?alt=media")
            if hasattr(resp, "iter_lines"):
                lines: Iterable[Any] = resp.iter_lines()
            else:
                lines = resp.text.splitlines()
            for raw in lines:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                line = raw.strip()
                if line:
                    yield json.loads(line)
            return
        inline = (output.get("inlinedResponses") or {}).get("inlinedResponses") or []
        for row in inline:
            yield row


# ----------------------------------------------------------------------
# bookkeeping (D2)
# ----------------------------------------------------------------------
def _load_jobs(conn) -> list[dict]:
    """簿記から未完了ジョブ一覧を読む (壊れ値・異形状は空として扱う)。"""
    try:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = %s", (_JOBS_SETTINGS_KEY,)
        ).fetchone()
    except psycopg.errors.UndefinedTable:
        # テーブル未作成 (v2 初期化前) は未保存として扱う
        return []
    data = row["value_json"] if row else None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return []
    return [j for j in jobs if isinstance(j, dict) and isinstance(j.get("name"), str)]


def _save_jobs(conn, jobs: list[dict]) -> None:
    """簿記へジョブ一覧を置換保存する (短いトランザクション・本体処理と排他しない)。

    処理中 (API 呼び) にロックを保持しないため日次ジョブと CLI の同時実行では
    後書き勝ちになり得るが、失われたエントリは「次回実行時に API 状態を再照合 →
    terminal なら簿記から落下」で自己修復する。
    """
    try:
        conn.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at) VALUES(%s, %s, %s)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (
                _JOBS_SETTINGS_KEY,
                json.dumps({"jobs": jobs}, ensure_ascii=False),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ----------------------------------------------------------------------
# 結果の適用 (stale guard)
# ----------------------------------------------------------------------
def _parse_row(row: dict) -> tuple[int, str, list[float] | None, str | None] | None:
    """結果行を ``(pid, submit_hash, vec, error)`` へ正規化する (不可解行は None)。

    ベクトルは json 由来の list をそのまま保持する (後段 window で即消費するため
    5,000 行一括の float 変換を避ける = メモリ節約)。
    """
    meta = row.get("metadata") if isinstance(row, dict) else None
    if not isinstance(meta, dict):
        return None
    try:
        pid = int(meta.get("key"))
    except (TypeError, ValueError):
        return None
    digest = meta.get("hash")
    digest = digest if isinstance(digest, str) else ""
    resp = row.get("response")
    values = (resp or {}).get("embedding", {}).get("values") if isinstance(resp, dict) else None
    if isinstance(values, list) and len(values) == EMBEDDING_DIM:
        return (pid, digest, values, None)
    err = row.get("error") or "empty/malformed embedding in result row"
    return (pid, digest, None, str(err)[:200])


def apply_batch_results(rows: Iterable[dict], *, progress_every: int = 500) -> dict:
    """完了ジョブの結果行を stale guard 付きで適用する。

    - ``metadata.hash`` が現在の ``compose_texts_for`` 結果と一致した行のみ
      upsert (1 行 = 1 commit・部分進捗を残す)。
    - 不一致 (submit 後に内容変化) は ``stale_skipped`` — 次サイクルで自然に
      再対象になる。``error`` 行は ``failed_rows`` (embedding 未挿入のまま
      翌日再試行)。物件が可視でなくなっていた行は ``missing``。
    - 接続は関数内で開き、結果行は到着順に ``_APPLY_WINDOW`` 件ずつ消費する
      (5,000 行分のベクトルを一括保持しない)。
    """
    stats = {"applied": 0, "stale_skipped": 0, "failed_rows": 0, "missing": 0}
    with open_connection() as conn:
        window: list[tuple[int, str, list[float] | None, str | None]] = []

        def flush() -> None:
            if not window:
                return
            composed = compose_texts_for(conn, [pid for pid, *_ in window])
            for pid, digest, vec, err in window:
                if err is not None:
                    stats["failed_rows"] += 1
                    print(f"  ! batch result failed property_id={pid}: {err}", file=sys.stderr)
                    continue
                cur = composed.get(pid)
                if cur is None:
                    stats["missing"] += 1
                    continue
                if cur[1] != digest:
                    stats["stale_skipped"] += 1
                    continue
                upsert_embedding(conn, pid, cur[0], vec)
                conn.commit()
                stats["applied"] += 1
            window.clear()

        for row in rows:
            parsed = _parse_row(row)
            if parsed is None:
                stats["failed_rows"] += 1
                print(
                    f"  ! batch result row is unattributable: {str(row)[:200]}", file=sys.stderr
                )
                continue
            window.append(parsed)
            if len(window) >= _APPLY_WINDOW:
                flush()
        flush()
    return stats


# ----------------------------------------------------------------------
# オーケストレーション (日次ジョブ / CLI 共通)
# ----------------------------------------------------------------------
def run_batch_sync(
    *,
    limit: int | None = None,
    wait_secs: int = 300,
    max_requests_per_batch: int = _MAX_REQUESTS_PER_BATCH,
    submit_only: bool = False,
    client: GeminiEmbeddingBatchClient | None = None,
    progress_every: int = 500,
) -> dict:
    """outstanding 適用 → pending submit → bounded 待機 → 完了分適用 の 1 サイクル。

    - **①**: 簿記上の未完了ジョブを API で再照合し、完了分を適用・terminal 分を
      簿記から落とす。
    - **②**: 未カバー / hash 不一致の可視物件のうち **①で未完了のまま残った
      ジョブの ``pids`` を除いて** JSONL ファイル経由で新規 submit する
      (ジョブは ``max_requests_per_batch`` (D4) ごとに分割)。
    - **③④**: ``wait_secs`` 秒相当 (``_POLL_INTERVAL_S`` 刻み) だけ待機し、
      この間に完了したジョブを適用する。小ジョブは実測数分で完了するため
      ほとんどのサイクルはここで即日反映される。未完了分は簿記に残し、
      翌日のジョブ / CLI 再実行の冒頭で適用される。

    ``submit_only=True`` は ③④ を省略する (手動 2 段運用)。
    ``client=None`` なら :class:`GeminiEmbeddingBatchClient` を生成する
    (GEMINI_API_KEY 必須)。日次ジョブは ``wait_secs=120`` で呼ぶ。
    """
    stats = {
        "candidates": 0,
        "pending": 0,
        "submitted_batches": 0,
        "submitted_requests": 0,
        "outstanding_done": 0,
        "outstanding_still_running": 0,
        "outstanding_dropped": 0,
        "applied": 0,
        "stale_skipped": 0,
        "failed_rows": 0,
        "missing": 0,
        "wait_secs": int(wait_secs),
        "submit_only": bool(submit_only),
    }
    if client is None:
        client = GeminiEmbeddingBatchClient()

    # ① outstanding ジョブの再照合と適用
    with open_connection() as conn:
        jobs = _load_jobs(conn)
    remaining: list[dict] = []
    for job in jobs:
        name = job["name"]
        try:
            info = client.get_batch(name)
        except BatchJobNotFoundError:
            stats["outstanding_dropped"] += 1
            print(f"  ! batch job disappeared (dropped): {name}", file=sys.stderr)
            continue
        state = info["state"]
        if state == _STATE_SUCCEEDED:
            res = apply_batch_results(
                client.iter_results(info["output"]), progress_every=progress_every
            )
            for key in ("applied", "stale_skipped", "failed_rows", "missing"):
                stats[key] += res[key]
            stats["outstanding_done"] += 1
            continue
        if state in _TERMINAL_STATES or info["error"]:
            stats["outstanding_dropped"] += 1
            print(
                f"  ! batch job {state or 'ERROR'} (dropped): {name} {info['error'] or ''}",
                file=sys.stderr,
            )
            continue
        job["state"] = state
        remaining.append(job)

    # ② pending 算出と submit (未完了ジョブが保有する pids は除外)
    covered: set[int] = set()
    for job in remaining:
        covered.update(int(p) for p in job.get("pids") or [])

    with open_connection() as conn:
        pids = [p for p in visible_property_ids(conn, limit) if p not in covered]
        stats["candidates"] = len(pids)
        pending: list[tuple[int, str, str]] = []
        existing_hashes: dict[int, str] = {}
        for start in range(0, len(pids), _APPLY_WINDOW):
            chunk = pids[start : start + _APPLY_WINDOW]
            composed = compose_texts_for(conn, chunk)
            rows = conn.execute(
                "SELECT property_id, model, search_text_hash FROM property_embeddings "
                f"WHERE property_id IN ({','.join('%s' for _ in chunk)})",
                chunk,
            )
            for r in rows:
                if r["model"] == EMBEDDING_MODEL:
                    existing_hashes[int(r["property_id"])] = r["search_text_hash"]
            for pid in chunk:
                text, digest = composed[pid]
                if existing_hashes.get(pid) != digest:
                    pending.append((pid, text, digest))
        stats["pending"] = len(pending)

        if pending:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            for i, start in enumerate(range(0, len(pending), max_requests_per_batch)):
                part = pending[start : start + max_requests_per_batch]
                display = f"{_DISPLAY_PREFIX}{stamp}-{i}"
                file_name = client.upload_input_file(build_input_jsonl(part), display)
                name = client.create_batch(file_name, display)
                remaining.append(
                    {
                        "name": name,
                        "display_name": display,
                        "request_count": len(part),
                        "pids": [pid for pid, *_ in part],
                        "submitted_at": datetime.now().isoformat(),
                        "state": "BATCH_STATE_PENDING",
                    }
                )
                stats["submitted_batches"] += 1
                stats["submitted_requests"] += len(part)
                # 作成は非冪等なので 1 ジョブごとに簿記へ反映する。分割 2 ジョブ目の
                # submit が失敗した (例: 一時 429) とき、1 ジョブ目が API 側にだけ
                # 存在する孤児になるのを防ぐ (pending 計算は読み取り専用なので
                # 同一接続での途中 commit は無害)。
                _save_jobs(conn, remaining)
                if progress_every and stats["submitted_requests"] % progress_every == 0:
                    print(
                        f"  ... submitted {stats['submitted_requests']}/{len(pending)} requests"
                    )
        _save_jobs(conn, remaining)

    # ③ bounded 待機 + ④ 完了分適用
    polls = max(0, int(wait_secs)) // _POLL_INTERVAL_S
    for _ in range(polls):
        if not remaining:
            break
        time.sleep(_POLL_INTERVAL_S)
        still: list[dict] = []
        for job in remaining:
            try:
                info = client.get_batch(job["name"])
            except BatchJobNotFoundError:
                stats["outstanding_dropped"] += 1
                continue
            state = info["state"]
            if state == _STATE_SUCCEEDED:
                res = apply_batch_results(
                    client.iter_results(info["output"]), progress_every=progress_every
                )
                for key in ("applied", "stale_skipped", "failed_rows", "missing"):
                    stats[key] += res[key]
                stats["outstanding_done"] += 1
                continue
            if state in _TERMINAL_STATES or info["error"]:
                stats["outstanding_dropped"] += 1
                print(
                    f"  ! batch job {state or 'ERROR'} (dropped): {job['name']}",
                    file=sys.stderr,
                )
                continue
            job["state"] = state
            still.append(job)
        remaining = still
    # 待機の有無にかかわらず最終状態を簿記へ反映する (空リストの保存で
    # 適用済みジョブが次サイクルも残るのを防ぐ)。
    with open_connection() as conn:
        _save_jobs(conn, remaining)
    stats["outstanding_still_running"] = len(remaining)
    return stats
