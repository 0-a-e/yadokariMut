#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""store.embeddings_batch (Gemini Batch API 経路・docs/embedding-batch-api-plan.md) のテスト.

実 API は呼ばない:

- build_input_jsonl: 1 行 = {request, metadata} 形状 (key=property_id・hash)
- GeminiEmbeddingBatchClient: resumable 2 段 upload / asyncBatchEmbedContent 作成 /
  metadata 平坦化 get / 404→BatchJobNotFoundError / 429 バックオフ再試行 /
  結果ダウンロード (responsesFile・inlinedResponses 両対応)
- apply_batch_results: hash 一致 upsert / stale (hash 不一致) スキップ /
  error 行・不可解行 / missing / window 境界
- run_batch_sync: submit (D4 分割・未完了ジョブ pids の二重 submit 防止) /
  outstanding 適用 / FAILED・404 落下 / bounded 待機での適用 / limit
- cmd_backfill_embeddings: batch 既定 / --mode sync / --dry-run / --submit-only
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

import store.embeddings as emb
import store.embeddings_batch as emb_batch
from store.embeddings import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    GeminiEmbeddingError,
    upsert_embedding,
)
from store.embeddings_batch import (
    BatchJobNotFoundError,
    GeminiEmbeddingBatchClient,
    apply_batch_results,
    build_input_jsonl,
    run_batch_sync,
)

SUCCEEDED = "BATCH_STATE_SUCCEEDED"
RUNNING = "BATCH_STATE_RUNNING"
FAILED = "BATCH_STATE_FAILED"


# --- 共有ヘルパ -----------------------------------------------------------


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fake_compose(prop, features, accesses, plans, campaigns):
    """title 依存の決定論的合成 (DOCUMENT_PREFIX 込みが本質ではないため同等物で代替)。"""
    return f"text: title:{prop.get('title')}|features:{','.join(sorted(features))}"


class _Resp:
    """requests の Response 最小フェイク (headers / json / text / iter_lines)。"""

    def __init__(
        self,
        status_code: int = 200,
        body: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
        lines: list[bytes | str] | None = None,
    ):
        self.status_code = status_code
        self._body = body
        self.text = text or (json.dumps(body, ensure_ascii=False) if body is not None else "")
        self.headers = headers or {}
        self._lines = lines

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body

    def iter_lines(self):
        return iter(self._lines or [])


class _Recorder:
    """requests モジュール互換 (post/get) の呼び出し記録器。"""

    def __init__(self, post_responses=(), get_responses=()):
        self.post_responses = list(post_responses)
        self.get_responses = list(get_responses)
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.post_calls.append(
            {"url": url, "json": json, "data": data, "headers": headers, "timeout": timeout}
        )
        resp = self.post_responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def get(self, url, headers=None, timeout=None):
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        resp = self.get_responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeOrchestrator:
    """run_batch_sync 用の DI クライアント (upload/create/get/iter を記録するだけ)。"""

    def __init__(self, states: dict[str, Any] | None = None, results: dict[str, list] | None = None):
        self.uploads: list[tuple[bytes, str]] = []
        self.creates: list[tuple[str, str]] = []
        self.gets: list[str] = []
        # name → 単一 state または get のたびに pop する state の列
        self.states = states or {}
        # responsesFile キー → 結果行の列 (iter_results が返す)
        self.results = results or {}
        self._seq = 0

    def _next_name(self) -> str:
        name = f"batches/fake{self._seq}"
        self._seq += 1
        return name

    def upload_input_file(self, data: bytes, display_name: str) -> str:
        self.uploads.append((data, display_name))
        return f"files/{display_name}"

    def create_batch(self, file_name: str, display_name: str) -> str:
        self.creates.append((file_name, display_name))
        return self._next_name()

    def get_batch(self, name: str) -> dict:
        self.gets.append(name)
        spec = self.states.get(name, RUNNING)
        if isinstance(spec, list):
            spec = spec.pop(0) if spec else RUNNING
        if spec == SUCCEEDED:
            key = f"files/batch-{name}"
            return {"state": spec, "stats": {}, "output": {"responsesFile": key}, "error": None}
        return {"state": spec, "stats": {}, "output": {}, "error": None}

    def iter_results(self, output: dict) -> list[dict]:
        return list(self.results.get(output["responsesFile"], []))


def _insert_property(conn, external_id, title="物件") -> int:
    return int(
        conn.execute(
            "INSERT INTO properties (source_site, external_id, title) "
            "VALUES (%s, %s, %s) RETURNING id",
            ("fakesite", external_id, title),
        ).fetchone()[0]
    )


def _load_saved_jobs():
    from store.pg import open_connection

    with open_connection() as conn:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = %s",
            (emb_batch._JOBS_SETTINGS_KEY,),
        ).fetchone()
    if not row:
        return []
    return row["value_json"].get("jobs", [])


@pytest.fixture()
def batch_env(tmp_v2_db, monkeypatch):
    """合成・hash を決定論化 + sleep を記録に置き換えた run_batch_sync 用環境。"""
    monkeypatch.setattr(emb, "compose_search_text", _fake_compose)
    monkeypatch.setattr(emb, "search_text_hash", _sha)
    sleeps: list[float] = []
    monkeypatch.setattr(emb_batch.time, "sleep", sleeps.append)
    return tmp_v2_db


def _result_row(pid: int, digest: str, vec: list[float] | None, error: str | None = None) -> dict:
    meta: dict[str, Any] = {"key": str(pid), "hash": digest}
    row: dict[str, Any] = {"metadata": meta}
    if error is not None:
        row["error"] = {"message": error}
    else:
        row["response"] = {"embedding": {"values": vec}}
    return row


# --- build_input_jsonl -----------------------------------------------------


class TestBuildInputJsonl:
    def test_line_shape(self):
        data = build_input_jsonl([(123, "text: 物件本文", "a" * 64)])
        lines = data.decode("utf-8").strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["metadata"] == {"key": "123", "hash": "a" * 64}
        req = row["request"]
        assert req["content"]["parts"][0]["text"] == "text: 物件本文"
        assert req["embedContentConfig"]["outputDimensionality"] == EMBEDDING_DIM
        # taskType は embedding-2 で no-op のため送らない
        assert "taskType" not in req

    def test_multiple_items_keep_order(self):
        data = build_input_jsonl([(2, "b", "h2"), (1, "a", "h1")])
        rows = [json.loads(line) for line in data.decode("utf-8").strip().splitlines()]
        assert [r["metadata"]["key"] for r in rows] == ["2", "1"]

    def test_empty_items(self):
        assert build_input_jsonl([]) == b""


# --- GeminiEmbeddingBatchClient -------------------------------------------


class TestGeminiEmbeddingBatchClient:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiEmbeddingError):
            GeminiEmbeddingBatchClient()

    def test_upload_input_file_two_step(self):
        rec = _Recorder(
            post_responses=[
                _Resp(200, headers={"x-goog-upload-url": "https://x/upload?upload_id=1"}),
                _Resp(200, body={"file": {"name": "files/abc123"}}),
            ]
        )
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)

        name = client.upload_input_file(b'{"a": 1}\n', "emb-x")

        assert name == "files/abc123"
        start, finalize = rec.post_calls
        assert start["url"] == "https://generativelanguage.googleapis.com/upload/v1beta/files"
        # API キーは 2 段とも送る (実キー検証で 403 になった回帰防止)
        assert start["headers"]["x-goog-api-key"] == "k"
        assert finalize["headers"]["x-goog-api-key"] == "k"
        assert start["headers"]["X-Goog-Upload-Protocol"] == "resumable"
        assert start["headers"]["X-Goog-Upload-Header-Content-Length"] == "9"
        assert start["headers"]["X-Goog-Upload-Header-Content-Type"] == "jsonl"
        assert finalize["url"] == "https://x/upload?upload_id=1"
        assert finalize["data"] == b'{"a": 1}\n'
        assert finalize["headers"]["X-Goog-Upload-Command"] == "upload, finalize"
        assert finalize["headers"]["X-Goog-Upload-Offset"] == "0"

    def test_upload_input_file_missing_url_raises(self):
        rec = _Recorder(post_responses=[_Resp(200, body={})])
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)
        with pytest.raises(GeminiEmbeddingError, match="x-goog-upload-url"):
            client.upload_input_file(b"x", "emb-x")

    def test_create_batch_request_shape(self):
        rec = _Recorder(post_responses=[_Resp(200, body={"name": "batches/j1"})])
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)

        name = client.create_batch("files/abc", "emb-x")

        assert name == "batches/j1"
        call = rec.post_calls[0]
        assert call["url"].endswith("/v1beta/models/gemini-embedding-2:asyncBatchEmbedContent")
        assert call["headers"] == {"x-goog-api-key": "k"}
        assert call["json"] == {
            "batch": {"displayName": "emb-x", "inputConfig": {"fileName": "files/abc"}}
        }

    def test_create_batch_unexpected_response_raises(self):
        rec = _Recorder(post_responses=[_Resp(200, body={"name": "not-a-batch-name"})])
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)
        with pytest.raises(GeminiEmbeddingError, match="unexpected job name"):
            client.create_batch("files/abc", "emb-x")

    def test_create_batch_malformed_response_raises(self):
        rec = _Recorder(post_responses=[_Resp(200, body={"unexpected": 1})])
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)
        with pytest.raises(GeminiEmbeddingError, match="unexpected response"):
            client.create_batch("files/abc", "emb-x")

    def test_get_batch_flattens_operation_metadata(self):
        rec = _Recorder(
            get_responses=[
                _Resp(
                    200,
                    body={
                        "name": "batches/j1",
                        "metadata": {
                            "state": RUNNING,
                            "batchStats": {"requestCount": "2"},
                            "output": {},
                        },
                    },
                )
            ]
        )
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)

        info = client.get_batch("batches/j1")

        assert rec.get_calls[0]["url"].endswith("/v1beta/batches/j1")
        assert rec.get_calls[0]["headers"] == {"x-goog-api-key": "k"}
        assert info["state"] == RUNNING
        assert info["stats"] == {"requestCount": "2"}

    def test_get_batch_404_raises_not_found(self):
        rec = _Recorder(get_responses=[_Resp(404, text="not found")])
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)
        with pytest.raises(BatchJobNotFoundError):
            client.get_batch("batches/gone")

    def test_429_retries_with_backoff(self, monkeypatch):
        rec = _Recorder(
            get_responses=[_Resp(429, text="rate"), _Resp(200, body={"metadata": {"state": RUNNING}})]
        )
        sleeps: list[float] = []
        monkeypatch.setattr(emb_batch.time, "sleep", sleeps.append)
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)

        info = client.get_batch("batches/j1")

        assert info["state"] == RUNNING
        assert len(rec.get_calls) == 2
        assert sleeps == [1]

    def test_client_error_does_not_retry(self):
        rec = _Recorder(get_responses=[_Resp(400, text="bad")] * 4)
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)
        with pytest.raises(GeminiEmbeddingError, match="400"):
            client.get_batch("batches/j1")
        assert len(rec.get_calls) == 1

    def test_iter_results_from_responses_file(self):
        row = _result_row(7, "h", [0.5] * EMBEDDING_DIM)
        rec = _Recorder(
            get_responses=[
                _Resp(200, lines=[json.dumps(row, ensure_ascii=False).encode("utf-8"), b""])
            ]
        )
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)

        rows = list(client.iter_results({"responsesFile": "files/batch-x"}))

        assert rec.get_calls[0]["url"].endswith("/download/v1beta/files/batch-x:download?alt=media")
        assert rows == [row]

    def test_iter_results_from_inlined_responses(self):
        row = _result_row(8, "h", [0.1] * EMBEDDING_DIM)
        rec = _Recorder()
        client = GeminiEmbeddingBatchClient(api_key="k", session=rec)

        rows = list(
            client.iter_results({"inlinedResponses": {"inlinedResponses": [row]}})
        )

        assert rows == [row]
        assert rec.get_calls == []  # ダウンロード無し


# --- apply_batch_results ---------------------------------------------------


class TestApplyBatchResults:
    @pytest.fixture()
    def apply_env(self, tmp_v2_db, monkeypatch):
        monkeypatch.setattr(emb, "compose_search_text", _fake_compose)
        monkeypatch.setattr(emb, "search_text_hash", _sha)
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "ap-1", title="駅近")
            p2 = _insert_property(conn, "ap-2", title="高層階")
            p3 = _insert_property(conn, "ap-3", title="失敗用")
            conn.commit()
        return {"p1": p1, "p2": p2, "p3": p3}

    def _current_compose(self, pid: int) -> tuple[str, str]:
        from store.pg import open_connection

        with open_connection() as conn:
            return emb.compose_texts_for(conn, [pid])[pid]

    def test_applies_matching_hash_and_skips_stale(self, apply_env):
        p1, p2 = apply_env["p1"], apply_env["p2"]
        text1, digest1 = self._current_compose(p1)
        vec = [0.25] * EMBEDDING_DIM
        rows = [
            _result_row(p1, digest1, vec),  # 一致 → 適用
            _result_row(p2, "stale" + "0" * 59, vec),  # 不一致 → stale スキップ
            _result_row(999, "0" * 64, vec),  # 存在しない → missing
            _result_row(p1, "0" * 64, None, error="boom"),  # error 行 → failed
        ]

        stats = apply_batch_results(rows)

        assert stats == {
            "applied": 1,
            "stale_skipped": 1,
            "failed_rows": 1,
            "missing": 1,
        }
        from store.pg import open_connection

        with open_connection() as conn:
            row = conn.execute(
                "SELECT model, search_text, search_text_hash FROM property_embeddings "
                "WHERE property_id = %s",
                (p1,),
            ).fetchone()
        assert row["model"] == EMBEDDING_MODEL
        assert row["search_text"] == text1
        assert row["search_text_hash"] == digest1
        # stale 行は書き込まれない
        with open_connection() as conn:
            assert (
                conn.execute(
                    "SELECT 1 FROM property_embeddings WHERE property_id = %s", (p2,)
                ).fetchone()
                is None
            )

    def test_window_flush_boundary(self, apply_env, monkeypatch):
        """_APPLY_WINDOW 越えでも全行が処理される (窓の clear 漏れがない)。"""
        monkeypatch.setattr(emb_batch, "_APPLY_WINDOW", 2)
        p1 = apply_env["p1"]
        p2 = apply_env["p2"]
        p3 = apply_env["p3"]
        _, d1 = self._current_compose(p1)
        _, d2 = self._current_compose(p2)
        _, d3 = self._current_compose(p3)
        vec = [0.1] * EMBEDDING_DIM
        rows = [
            _result_row(p1, d1, vec),
            _result_row(p2, d2, vec),
            _result_row(p3, d3, vec),
        ]

        stats = apply_batch_results(rows)

        assert stats["applied"] == 3
        assert stats["stale_skipped"] == 0

    def test_unattributable_row_counts_as_failed(self, apply_env):
        stats = apply_batch_results([{"no-metadata": True}, {"metadata": {"key": "x"}}])
        assert stats["failed_rows"] == 2
        assert stats["applied"] == 0


# --- run_batch_sync --------------------------------------------------------


class TestRunBatchSync:
    def test_submit_only_submits_pending_and_records_jobs(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "bs-1", title="A")
            p2 = _insert_property(conn, "bs-2", title="B")
            conn.commit()
        fake = _FakeOrchestrator()

        stats = run_batch_sync(client=fake, wait_secs=0)

        assert stats["candidates"] == 2
        assert stats["pending"] == 2
        assert stats["submitted_batches"] == 1
        assert stats["submitted_requests"] == 2
        assert stats["outstanding_still_running"] == 1
        assert len(fake.uploads) == 1
        data, display = fake.uploads[0]
        assert display.startswith("emb-")
        pids = [
            json.loads(line)["metadata"]["key"]
            for line in data.decode("utf-8").strip().splitlines()
        ]
        assert sorted(int(p) for p in pids) == sorted([p1, p2])
        jobs = _load_saved_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "batches/fake0"
        assert sorted(jobs[0]["pids"]) == sorted([p1, p2])
        assert jobs[0]["request_count"] == 2
        assert jobs[0]["state"] == "BATCH_STATE_PENDING"

    def test_splits_jobs_by_max_requests_per_batch(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            for i in range(3):
                _insert_property(conn, f"sp-{i}", title=f"S{i}")
            conn.commit()
        fake = _FakeOrchestrator()

        stats = run_batch_sync(client=fake, wait_secs=0, max_requests_per_batch=2)

        assert stats["pending"] == 3
        assert stats["submitted_batches"] == 2
        assert stats["submitted_requests"] == 3
        jobs = _load_saved_jobs()
        assert [j["request_count"] for j in jobs] == [2, 1]

    def test_mid_submit_failure_keeps_created_jobs_in_bookkeeping(self, batch_env):
        """分割 2 ジョブ目の create 失敗でも 1 ジョブ目が簿記に残る (孤児防止)。"""
        from store.pg import open_connection

        with open_connection() as conn:
            for i in range(3):
                _insert_property(conn, f"mf-{i}", title=f"M{i}")
            conn.commit()

        class HalfFailingClient(_FakeOrchestrator):
            def __init__(self):
                super().__init__()
                self.creates_done = 0

            def create_batch(self, file_name, display_name):
                self.creates_done += 1
                if self.creates_done == 2:
                    raise GeminiEmbeddingError("Batch API 429 (transient)")
                return super().create_batch(file_name, display_name)

        fake = HalfFailingClient()
        with pytest.raises(GeminiEmbeddingError):
            run_batch_sync(client=fake, wait_secs=0, max_requests_per_batch=2)

        jobs = _load_saved_jobs()
        assert len(jobs) == 1
        assert jobs[0]["request_count"] == 2
        assert len(jobs[0]["pids"]) == 2

    def test_applies_outstanding_then_resubmits_stale_rest(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "oa-1", title="A")
            p2 = _insert_property(conn, "oa-2", title="B")
            conn.commit()
        fake = _FakeOrchestrator()
        run_batch_sync(client=fake, wait_secs=0)  # job0 = [p1, p2]

        # job0 は完了: p1 は submit 時 hash のまま (適用)・p2 は内容変化 (stale)
        with open_connection() as conn:
            _, d1 = emb.compose_texts_for(conn, [p1])[p1]
        vec = [0.3] * EMBEDDING_DIM
        results = {
            "files/batch-batches/fake0": [
                _result_row(p1, d1, vec),
                _result_row(p2, "old" + "0" * 61, vec),
            ]
        }
        fake2 = _FakeOrchestrator(
            states={"batches/fake0": SUCCEEDED},
            results=results,
        )
        # _FakeOrchestrator は新規ジョブ名を fake0 から採番するため、
        # states の job0 と新規採番が衝突しないよう seq を進めておく
        fake2._seq = 1

        stats = run_batch_sync(client=fake2, wait_secs=0)

        assert stats["outstanding_done"] == 1
        assert stats["applied"] == 1
        assert stats["stale_skipped"] == 1
        # stale で残った p2 のみ再 submit
        assert stats["pending"] == 1
        assert stats["submitted_batches"] == 1
        jobs = _load_saved_jobs()
        assert len(jobs) == 1
        assert jobs[0]["pids"] == [p2]
        with open_connection() as conn:
            row = conn.execute(
                "SELECT search_text_hash FROM property_embeddings WHERE property_id = %s",
                (p1,),
            ).fetchone()
        assert row["search_text_hash"] == d1

    def test_skips_pids_covered_by_still_running_jobs(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "dc-1", title="A")
            conn.commit()
        fake = _FakeOrchestrator(states={"batches/fake0": RUNNING})
        run_batch_sync(client=fake, wait_secs=0)  # job0 = [p1]

        fake2 = _FakeOrchestrator(states={"batches/fake0": RUNNING})
        fake2._seq = 1
        stats = run_batch_sync(client=fake2, wait_secs=0)

        # job0 未完了の pids は再 submit しない (二重送信防止)
        assert stats["pending"] == 0
        assert stats["submitted_batches"] == 0
        assert stats["outstanding_still_running"] == 1
        assert fake2.uploads == []
        assert len(_load_saved_jobs()) == 1

    def test_failed_job_is_dropped_and_resubmitted(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "fd-1", title="A")
            conn.commit()
        fake = _FakeOrchestrator()
        run_batch_sync(client=fake, wait_secs=0)  # job0 = [p1]

        fake2 = _FakeOrchestrator(states={"batches/fake0": FAILED})
        fake2._seq = 1
        stats = run_batch_sync(client=fake2, wait_secs=0)

        assert stats["outstanding_dropped"] == 1
        assert stats["pending"] == 1  # p1 は embedding 未挿入のまま再対象
        assert stats["submitted_batches"] == 1
        jobs = _load_saved_jobs()
        assert len(jobs) == 1
        assert jobs[0]["pids"] == [p1]

    def test_disappeared_job_is_dropped(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "dp-1", title="A")
            conn.commit()
        fake = _FakeOrchestrator()
        run_batch_sync(client=fake, wait_secs=0)

        class GoneClient(_FakeOrchestrator):
            def get_batch(self, name):
                self.gets.append(name)
                if name == "batches/fake0":
                    raise BatchJobNotFoundError("gone")
                return super().get_batch(name)

        fake2 = GoneClient()
        fake2._seq = 1
        stats = run_batch_sync(client=fake2, wait_secs=0)

        assert stats["outstanding_dropped"] == 1
        assert stats["submitted_batches"] == 1  # p1 を再 submit

    def test_bounded_wait_applies_completed_jobs(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "bw-1", title="A")
            _, d1 = emb.compose_texts_for(conn, [p1])[p1]
            conn.commit()
        # states: poll 1 で RUNNING・poll 2 で SUCCEEDED (wait_secs=60 = 2 polls)
        states = {"batches/fake0": [RUNNING, SUCCEEDED]}
        results = {"files/batch-batches/fake0": [_result_row(p1, d1, [0.2] * EMBEDDING_DIM)]}
        fake = _FakeOrchestrator(states=states, results=results)

        stats = run_batch_sync(client=fake, wait_secs=60)

        assert stats["submitted_batches"] == 1
        assert stats["outstanding_done"] == 1
        assert stats["applied"] == 1
        assert stats["outstanding_still_running"] == 0
        assert len(fake.gets) == 2  # poll × 2 (step① は outstanding 無しで skip)
        # 適用済みジョブは簿記から落ちている (空リストが保存される)
        assert _load_saved_jobs() == []

    def test_existing_hash_skips_submission(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "ex-1", title="A")
            text, digest = emb.compose_texts_for(conn, [p1])[p1]
            upsert_embedding(conn, p1, text, [0.5] * EMBEDDING_DIM)
            conn.commit()
        fake = _FakeOrchestrator()

        stats = run_batch_sync(client=fake, wait_secs=0)

        assert stats["pending"] == 0
        assert stats["submitted_batches"] == 0
        assert _load_saved_jobs() == []

    def test_limit_caps_candidates(self, batch_env):
        from store.pg import open_connection

        with open_connection() as conn:
            for i in range(3):
                _insert_property(conn, f"lm-{i}", title=f"L{i}")
            conn.commit()
        fake = _FakeOrchestrator()

        stats = run_batch_sync(client=fake, wait_secs=0, limit=2)

        assert stats["candidates"] == 2
        assert stats["pending"] == 2
        assert stats["submitted_requests"] == 2

    def test_missing_api_key_raises_without_client(self, batch_env, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiEmbeddingError):
            run_batch_sync(wait_secs=0)


# --- CLI -------------------------------------------------------------------


def _args(**kw) -> argparse.Namespace:
    defaults = {
        "limit": None,
        "dry_run": False,
        "mode": "batch",
        "wait_secs": 300,
        "batch_size": 5000,
        "submit_only": False,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestCmdBackfillEmbeddings:
    def test_batch_is_default_and_forwards_flags(self, batch_env, monkeypatch, capsys):
        import cli

        calls: dict[str, Any] = {}

        def fake_run(**kw):
            calls.update(kw)
            return {
                "candidates": 1,
                "pending": 1,
                "submitted_batches": 1,
                "submitted_requests": 1,
                "applied": 0,
                "stale_skipped": 0,
                "failed_rows": 0,
                "missing": 0,
                "outstanding_still_running": 1,
            }

        monkeypatch.setattr("store.embeddings_batch.run_batch_sync", fake_run)

        rc = cli.cmd_backfill_embeddings(
            _args(limit=5, wait_secs=10, batch_size=7, submit_only=True)
        )

        assert rc == 0
        assert calls["limit"] == 5
        assert calls["wait_secs"] == 10
        assert calls["max_requests_per_batch"] == 7
        assert calls["submit_only"] is True
        assert "[BATCH]" in capsys.readouterr().out

    def test_sync_mode_uses_serial_embedcontent(self, batch_env, monkeypatch, capsys):
        import cli
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "cli-1", title="A")
            conn.commit()
        # 実 sync 経路を通す (HTTP だけフェイク・API キーは env)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        rec = _Recorder(post_responses=[_Resp(body={"embedding": {"values": [0.4] * EMBEDDING_DIM}})])
        monkeypatch.setattr(emb.requests, "post", rec.post)

        rc = cli.cmd_backfill_embeddings(_args(mode="sync", limit=1))

        assert rc == 0
        assert "[APPLIED]" in capsys.readouterr().out
        assert len(rec.post_calls) == 1
        assert "taskType" not in rec.post_calls[0]["json"]
        with open_connection() as conn:
            row = conn.execute(
                "SELECT search_text FROM property_embeddings WHERE property_id = %s", (p1,)
            ).fetchone()
        # sync 経路も DOCUMENT_PREFIX 込みの text を格納する
        assert row["search_text"].startswith("text: ")

    def test_dry_run_reports_without_api(self, batch_env, capsys):
        import cli
        from store.pg import open_connection

        with open_connection() as conn:
            _insert_property(conn, "cli-dry", title="A")
            conn.commit()

        rc = cli.cmd_backfill_embeddings(_args(dry_run=True))

        assert rc == 0
        assert "[DRY-RUN]" in capsys.readouterr().out
        assert _load_saved_jobs() == []
