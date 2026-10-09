#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""store.embeddings (Phase 7a・pgvector embedding 管理) のテスト.

- vector_literal の往復精度
- GeminiEmbeddingClient: リクエスト形状 (taskType / outputDimensionality /
  x-goog-api-key)・429→バックオフリトライ・次元不一致・API キー無し
  (実 API は呼ばない・requests.post / time.sleep を monkeypatch)
- upsert_embedding: INSERT / ON CONFLICT UPDATE / embedding の文字列返却
- backfill_embeddings: 新規埋め・hash 一致スキップ・title 変更検知・
  model 不一致再生成・limit・dry_run・1 件失敗で止まらない
- embed_query_cached: lru_cache によるクエリ embed 呼び吸収
- embedding_coverage: 可視 (active OR shortlist saved/hide/reject) 集計

並行実装中の domain.embedding_text が未着でもテストが成立するよう、
import 失敗時のみ契約どおり (compose=title 由来の決定論的合成 /
hash=SHA256 hex) のスタブを sys.modules に入れる。個々のテストは
store.embeddings の束縛名を monkeypatch して決定論化する。
"""

from __future__ import annotations

import hashlib
import types

import pytest

try:
    import domain.embedding_text  # noqa: F401
except ImportError:
    _stub = types.ModuleType("domain.embedding_text")

    def _stub_compose(prop, features, accesses, plans, campaigns):
        return f"title:{prop.get('title')}|features:{','.join(sorted(features))}"

    _stub.compose_search_text = _stub_compose
    _stub.search_text_hash = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    import sys

    sys.modules["domain.embedding_text"] = _stub

import store.embeddings as emb
from store.embeddings import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    GeminiEmbeddingClient,
    GeminiEmbeddingError,
    backfill_embeddings,
    embedding_coverage,
    embed_query_cached,
    upsert_embedding,
    vector_literal,
)

# --- 共有ヘルパ -----------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fake_compose(prop, features, accesses, plans, campaigns):
    """title 依存の決定論的合成 (hash 変更検知テストのため title を含む)。"""
    return f"title:{prop.get('title')}|features:{','.join(sorted(features))}"


class _Resp:
    """requests.post 戻り値の最小フェイク。"""

    def __init__(self, status_code=200, values=None, text=""):
        self.status_code = status_code
        self.text = text
        self._values = values

    def json(self):
        return {"embedding": {"values": self._values}}


class _Recorder:
    """requests.post / session.post を差し替える呼び出し記録器。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeClient:
    """backfill 用の embed_document フェイク (固定ベクトル返却・呼び記録)。"""

    def __init__(self, vec=None, fail_texts=()):
        self.vec = vec if vec is not None else [0.25] * EMBEDDING_DIM
        self.fail_texts = set(fail_texts)
        self.calls = []

    def embed_document(self, text):
        self.calls.append(text)
        if text in self.fail_texts:
            raise GeminiEmbeddingError("fake failure")
        return list(self.vec)


def _insert_property(conn, external_id, title="物件", source_site="fakesite"):
    """properties 最小列 INSERT (IDENTITY id を RETURNING)。"""
    return int(
        conn.execute(
            "INSERT INTO properties (source_site, external_id, title) "
            "VALUES (%s, %s, %s) RETURNING id",
            (source_site, external_id, title),
        ).fetchone()[0]
    )


def _set_shortlist(conn, property_id, status):
    conn.execute(
        "INSERT INTO property_shortlists (property_id, status, updated_at) "
        "VALUES (%s, %s, %s)",
        (property_id, status, "2026-01-01T00:00:00"),
    )


def _parse_embedding(text: str) -> list[float]:
    assert isinstance(text, str) and text.startswith("[") and text.endswith("]")
    return [float(x) for x in text[1:-1].split(",")]


# --- vector_literal -------------------------------------------------------


class TestVectorLiteral:
    def test_roundtrip_exact(self):
        vec = [0.1, 1 / 3, -2.718281828459045, 1e-9, 0.0, 12345.6789]
        parsed = [float(x) for x in vector_literal(vec)[1:-1].split(",")]
        assert parsed == vec  # .17g により float64 往復で誤差ゼロ

    def test_format_shape(self):
        s = vector_literal([0.5, 1.0])
        assert s == "[0.5,1]"
        assert s.startswith("[") and s.endswith("]")

    def test_single_value(self):
        assert float(vector_literal([3.25])[1:-1]) == 3.25


# --- GeminiEmbeddingClient ------------------------------------------------


class TestGeminiEmbeddingClient:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiEmbeddingError):
            GeminiEmbeddingClient()

    def test_embed_document_request_shape(self, monkeypatch):
        rec = _Recorder([_Resp(values=[0.5] * EMBEDDING_DIM)])
        monkeypatch.setattr(emb.requests, "post", rec)
        client = GeminiEmbeddingClient(api_key="key-abc")

        out = client.embed_document("text: 本文テキスト")

        assert out == [0.5] * EMBEDDING_DIM
        assert len(rec.calls) == 1
        call = rec.calls[0]
        assert call["url"] == (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-embedding-2:embedContent"
        )
        # taskType は embedding-2 で no-op (docs/embedding-batch-api-plan.md §2-3) のため送らない
        assert "taskType" not in call["json"]
        assert call["json"]["outputDimensionality"] == EMBEDDING_DIM
        assert call["json"]["content"]["parts"][0]["text"] == "text: 本文テキスト"
        assert call["headers"]["x-goog-api-key"] == "key-abc"
        assert call["timeout"] == 30

    def test_embed_query_prompt_instruction(self, monkeypatch):
        rec = _Recorder([_Resp(values=[0.1] * EMBEDDING_DIM)])
        monkeypatch.setattr(emb.requests, "post", rec)
        client = GeminiEmbeddingClient(api_key="key-abc")

        client.embed_query("駅近")

        # クエリ側の非対称指示は QUERY_PREFIX 接頭 (docs/embedding-batch-api-plan.md §4-4)
        assert "taskType" not in rec.calls[0]["json"]
        assert rec.calls[0]["json"]["content"]["parts"][0]["text"] == emb.QUERY_PREFIX + "駅近"

    def test_api_key_from_env(self, monkeypatch):
        rec = _Recorder([_Resp(values=[0.1] * EMBEDDING_DIM)])
        monkeypatch.setattr(emb.requests, "post", rec)
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        client = GeminiEmbeddingClient()  # api_key 未指定 → env を見る

        client.embed_query("q")

        assert rec.calls[0]["headers"]["x-goog-api-key"] == "env-key"

    def test_429_retries_with_backoff_then_succeeds(self, monkeypatch):
        rec = _Recorder(
            [
                _Resp(429, text="rate limited"),
                _Resp(429, text="rate limited"),
                _Resp(values=[0.7] * EMBEDDING_DIM),
            ]
        )
        monkeypatch.setattr(emb.requests, "post", rec)
        sleeps: list[float] = []
        monkeypatch.setattr(emb.time, "sleep", sleeps.append)
        client = GeminiEmbeddingClient(api_key="k")

        out = client.embed_document("text")

        assert out == [0.7] * EMBEDDING_DIM
        assert len(rec.calls) == 3
        assert sleeps == [1, 2]  # 指数バックオフ 1s/2s/4s の途中まで

    def test_5xx_exhausts_retries(self, monkeypatch):
        rec = _Recorder([_Resp(500, text="boom")] * 4)
        monkeypatch.setattr(emb.requests, "post", rec)
        sleeps: list[float] = []
        monkeypatch.setattr(emb.time, "sleep", sleeps.append)
        client = GeminiEmbeddingClient(api_key="k")

        with pytest.raises(GeminiEmbeddingError):
            client.embed_document("text")

        assert len(rec.calls) == 4  # 初回 + リトライ 3 回
        assert sleeps == [1, 2, 4]

    def test_client_error_does_not_retry(self, monkeypatch):
        rec = _Recorder([_Resp(400, text="bad request")])
        monkeypatch.setattr(emb.requests, "post", rec)
        monkeypatch.setattr(emb.time, "sleep", lambda s: None)
        client = GeminiEmbeddingClient(api_key="k")

        with pytest.raises(GeminiEmbeddingError):
            client.embed_document("text")

        assert len(rec.calls) == 1  # 4xx は即失敗

    def test_dim_mismatch_raises(self, monkeypatch):
        rec = _Recorder([_Resp(values=[0.1] * 100)])
        monkeypatch.setattr(emb.requests, "post", rec)
        client = GeminiEmbeddingClient(api_key="k")

        with pytest.raises(GeminiEmbeddingError, match="dim mismatch"):
            client.embed_document("text")


# --- embed_query_cached ---------------------------------------------------


class TestEmbedQueryCached:
    def test_cache_absorbs_repeat_calls(self, monkeypatch):
        calls = []

        class FakeCli:
            def embed_query(self, text):
                calls.append(text)
                return [0.3] * EMBEDDING_DIM

        monkeypatch.setattr(emb, "GeminiEmbeddingClient", FakeCli)
        embed_query_cached.cache_clear()
        try:
            v1 = embed_query_cached("駅近")
            v2 = embed_query_cached("駅近")
            v3 = embed_query_cached("静か")
            assert calls == ["駅近", "静か"]  # 同一クエリの count+iter 2 回目は吸収
            assert v1 == v2 == [0.3] * EMBEDDING_DIM
            assert len(v3) == EMBEDDING_DIM
        finally:
            embed_query_cached.cache_clear()  # 他テストへのキャッシュ漏出防止


# --- DB 系 (isolated_db: テンプレート DB 複製パターン) --------------------


class TestUpsertEmbedding:
    def test_insert_then_update_same_property(self, tmp_v2_db):
        from store.pg import open_connection

        with open_connection() as conn:
            pid = _insert_property(conn, "up-1", title="物件 up1")
            vec1 = [0.5, -0.25] + [0.0] * (EMBEDDING_DIM - 2)
            upsert_embedding(conn, pid, "検索テキスト1", vec1)
            conn.commit()

            row = conn.execute(
                "SELECT model, dim, search_text, search_text_hash, embedding "
                "FROM property_embeddings WHERE property_id = %s",
                (pid,),
            ).fetchone()
            assert row["model"] == EMBEDDING_MODEL
            assert row["dim"] == EMBEDDING_DIM
            assert row["search_text"] == "検索テキスト1"
            assert row["search_text_hash"] == _sha("検索テキスト1")
            assert _parse_embedding(row["embedding"]) == pytest.approx(vec1, rel=1e-6)

            # 同一 property_id の再 upsert → UPDATE (行数 1・中身差し替わり)
            vec2 = [0.1] * EMBEDDING_DIM
            upsert_embedding(conn, pid, "検索テキスト2", vec2)
            conn.commit()

            rows = conn.execute(
                "SELECT search_text, search_text_hash, embedding "
                "FROM property_embeddings WHERE property_id = %s",
                (pid,),
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["search_text"] == "検索テキスト2"
            assert rows[0]["search_text_hash"] == _sha("検索テキスト2")
            assert _parse_embedding(rows[0]["embedding"]) == pytest.approx(vec2, rel=1e-6)


class TestEmbeddingCoverage:
    def test_counts_visible_and_embedded(self, tmp_v2_db):
        from store.pg import open_connection

        with open_connection() as conn:
            active = _insert_property(conn, "cov-a", title="A")  # 可視 (active)
            saved = _insert_property(conn, "cov-s", title="B")  # 可視 (saved)
            hidden = _insert_property(conn, "cov-h", title="C")  # 不可視 (無判定)
            conn.execute(
                "UPDATE properties SET is_active = FALSE WHERE id IN (%s, %s)",
                (saved, hidden),
            )
            _set_shortlist(conn, saved, "saved")
            conn.commit()

            assert embedding_coverage(conn) == {"visible_total": 2, "embedded": 0}

            upsert_embedding(conn, active, "t-a", [0.1] * EMBEDDING_DIM)
            upsert_embedding(conn, hidden, "t-h", [0.1] * EMBEDDING_DIM)  # 不可視は算外
            conn.commit()

            assert embedding_coverage(conn) == {"visible_total": 2, "embedded": 1}


class TestBackfillEmbeddings:
    @pytest.fixture()
    def emb_env(self, tmp_v2_db, monkeypatch):
        """合成・hash を決定論化した DB テスト用環境。"""
        monkeypatch.setattr(emb, "compose_search_text", _fake_compose)
        monkeypatch.setattr(emb, "search_text_hash", _sha)
        return tmp_v2_db

    def test_embeds_pending_then_skips_unchanged_then_detects_title_change(self, emb_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "bf-1", title="駅近ワンルーム")
            p2 = _insert_property(conn, "bf-2", title="静かな高層階")
            conn.commit()

        fc = FakeClient()
        res1 = backfill_embeddings(client=fc)
        assert res1 == {
            "candidates": 2,
            "pending": 2,
            "embedded": 2,
            "skipped_unchanged": 0,
            "failed": 0,
            "dry_run": False,
        }
        assert len(fc.calls) == 2  # 物件ごとに 1 回

        with open_connection() as conn:
            rows = {
                int(r["property_id"]): r
                for r in conn.execute(
                    "SELECT property_id, model, dim, search_text, search_text_hash "
                    "FROM property_embeddings"
                )
            }
        assert set(rows) == {p1, p2}
        assert rows[p1]["model"] == EMBEDDING_MODEL
        assert rows[p1]["dim"] == EMBEDDING_DIM
        assert rows[p1]["search_text"] == "title:駅近ワンルーム|features:"
        assert rows[p1]["search_text_hash"] == _sha(rows[p1]["search_text"])

        # 再実行: hash 一致のため全件スキップ (API 呼びも upsert も無し)
        res2 = backfill_embeddings(client=fc)
        assert res2["pending"] == 0
        assert res2["embedded"] == 0
        assert res2["skipped_unchanged"] == 2
        assert len(fc.calls) == 2

        # title 変更 → 合成テキストが変わり hash 不一致 → 1 件だけ再生成
        with open_connection() as conn:
            conn.execute("UPDATE properties SET title = %s WHERE id = %s", ("リノベ済み", p1))
            conn.commit()

        res3 = backfill_embeddings(client=fc)
        assert res3["pending"] == 1
        assert res3["embedded"] == 1
        assert res3["skipped_unchanged"] == 1
        assert res3["failed"] == 0
        assert len(fc.calls) == 3

        with open_connection() as conn:
            row = conn.execute(
                "SELECT search_text FROM property_embeddings WHERE property_id = %s", (p1,)
            ).fetchone()
            assert row["search_text"] == "title:リノベ済み|features:"

    def test_regenerates_on_model_mismatch(self, emb_env):
        from store.pg import open_connection

        with open_connection() as conn:
            _insert_property(conn, "bf-model", title="M")
            conn.commit()

        backfill_embeddings(client=FakeClient())
        with open_connection() as conn:
            conn.execute("UPDATE property_embeddings SET model = 'gemini-embedding-1'")
            conn.commit()

        res = backfill_embeddings(client=FakeClient())
        assert res["pending"] == 1  # model 不一致で全再生成対象
        assert res["embedded"] == 1
        assert res["skipped_unchanged"] == 0
        with open_connection() as conn:
            assert (
                conn.execute("SELECT model FROM property_embeddings").fetchone()["model"]
                == EMBEDDING_MODEL
            )

    def test_limit_takes_first_ids(self, emb_env):
        from store.pg import open_connection

        with open_connection() as conn:
            for i in range(3):
                _insert_property(conn, f"bf-lim-{i}", title=f"L{i}")
            conn.commit()

        res = backfill_embeddings(client=FakeClient(), limit=1)
        assert res["candidates"] == 1  # id 昇順の先頭 N 件
        assert res["embedded"] == 1
        with open_connection() as conn:
            assert int(conn.execute("SELECT COUNT(*) FROM property_embeddings").fetchone()[0]) == 1

    def test_dry_run_counts_without_api_or_rows(self, emb_env):
        from store.pg import open_connection

        with open_connection() as conn:
            _insert_property(conn, "bf-dry-1", title="D1")
            _insert_property(conn, "bf-dry-2", title="D2")
            conn.commit()

        fc = FakeClient()
        res = backfill_embeddings(client=fc, dry_run=True)
        assert res == {
            "candidates": 2,
            "pending": 2,
            "embedded": 0,
            "skipped_unchanged": 0,
            "failed": 0,
            "dry_run": True,
        }
        assert fc.calls == []  # dry_run は API を呼ばない
        with open_connection() as conn:
            assert int(conn.execute("SELECT COUNT(*) FROM property_embeddings").fetchone()[0]) == 0

        # dry_run の計上後も本番実行は通常どおり全件埋める
        res2 = backfill_embeddings(client=fc)
        assert res2["embedded"] == 2

    def test_single_failure_does_not_stop_batch(self, emb_env):
        from store.pg import open_connection

        with open_connection() as conn:
            p1 = _insert_property(conn, "bf-fail-1", title="成功する物件")
            p2 = _insert_property(conn, "bf-fail-2", title="失敗する物件")
            conn.commit()

        fc = FakeClient(fail_texts={_fake_compose({"title": "失敗する物件"}, [], [], [], [])})
        res = backfill_embeddings(client=fc)
        assert res["pending"] == 2
        assert res["embedded"] == 1
        assert res["failed"] == 1
        with open_connection() as conn:  # 失敗後も接続は健在・成功分だけ行が残る
            ids = {
                int(r["property_id"]) for r in conn.execute("SELECT property_id FROM property_embeddings")
            }
        assert ids == {p1}
        assert p2 not in ids
