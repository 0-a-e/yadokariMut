"""pgvector 意味検索の embedding 管理モジュール (PG移行 Phase 7a・E7)。

docs/sqlite-pg-migration-plan.md §4 Phase 7 / §2 E7・docs/embedding-batch-api-plan.md:

- モデルは ``gemini-embedding-2``・3072 次元・``GEMINI_API_KEY`` (E7 確定)。
- クライアントはネイティブ ``models.embedContent`` API を requests 直叩き
  (OpenAI 互換レイヤーは taskType を制御できないため不採用)。
- **taskType は廃止** (2026-10-09 実測: embedding-2 では DOCUMENT/QUERY/なしで
  ベクトル完全一致 = 完全な no-op・docs/embedding-batch-api-plan.md §2-3)。
  非対称検索はドキュメント準拠のプロンプト指示で行う — 格納側は
  ``compose_search_text`` が ``DOCUMENT_PREFIX`` (``text: ``) を含め、
  検索側は :meth:`GeminiEmbeddingClient.embed_query` が ``QUERY_PREFIX``
  (``task: search result | query: ``) を接頭する。

設計根拠 (同計画 §4 Phase 7a):

- **embedding 生成はバッチのみ**で、スクレイプ upsert の同期パスには入れない。
  外部 API (レート制限・障害) をスクレイプ信頼性から分離するため。増分追従は
  ①日次 APScheduler ジョブ ②CLI ``backfill-embeddings`` の入口から
  Batch API 経路 (:mod:`store.embeddings_batch`・既定) または sync 経路
  (:func:`backfill_embeddings`・``--mode sync`` のフォールバック) を呼ぶ。
- **HNSW インデックスは不採用** (Alembic 0005 も同一判断): 8k 行規模は seq scan
  でも全件距離計算が数十 ms・recall 100%。物件数 5 万+ または検索レイテンシ
  問題化で 0006 として HNSW + hnsw.iterative_scan を追加する。
- 変更検知は ``search_text_hash`` (SHA256・schema_meta の feature_dict_hash と
  同型の「内容ハッシュ差分同期」慣習)。モデル差し替えは ``model`` 値不一致で
  全件再生成、内容変化は hash 不一致の対象行のみ再生成。
"""

from __future__ import annotations

import functools
import os
import sys
import time
from typing import Any

import requests

from domain.embedding_text import (
    DOCUMENT_PREFIX,
    compose_search_text,
    search_text_hash,
)
from store.pg import open_connection

# 注意: store.queries.* をモジュールレベルで import しないこと。
# queries/buildings.py が逆に本モジュール (EMBEDDING_MODEL / embed_query_cached /
# vector_literal) を import するため、ここで _common を読むと
# store.embeddings → store.queries.__init__ → buildings → store.embeddings の
# 循環 import になる。compose_texts_for 内での遅延 import (cli.py と同じ慣習) で回避。

EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIM = 3072
EMBEDDING_API_ENV = "GEMINI_API_KEY"

# 検索クエリ側のプロンプト指示 (ドキュメント準拠・格納側は DOCUMENT_PREFIX)。
QUERY_PREFIX = "task: search result | query: "

_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{EMBEDDING_MODEL}:embedContent"
)
_TIMEOUT_S = 30
# 429/5xx に対する指数バックオフ再試行: 初回 + 3 回 (待ち 1s/2s/4s)。
_RETRY_ATTEMPTS = 4

# backfill の候補一括取得チャンク幅 (reparse-* / 検索系と同じ 500 件進捗粒度)。
_CANDIDATE_CHUNK = 500

# 可視部屋の述語 (SSOT: store/queries/search.py:43 と同一式)。
# p.is_active OR ショートリスト saved/hide/reject — ユーザーが関心を示した
# 非掲載部屋も検索対象となるため embedding カバーの対象に含める。
_VISIBLE_PREDICATE = "(p.is_active OR s.status IN ('saved', 'hide', 'reject'))"


class GeminiEmbeddingError(RuntimeError):
    """Gemini embedContent API 呼び出しの失敗 (認証・レスポンス形式・リトライ枯渇)。"""


class GeminiEmbeddingClient:
    """ネイティブ Gemini ``embedContent`` クライアント (requests 直叩き)。

    - ``api_key`` 未指定時は ``os.environ[EMBEDDING_API_ENV]`` を見る。無ければ
      GeminiEmbeddingError (起動時 fail-fast・DEEPSEEK_* と同パターン)。
    - ``session`` は DI 点 (requests.Session 互換の ``post`` を持つオブジェクト
      なら何でも良い)。既定は requests モジュール直叩き。
    - 429/5xx (とネットワーク断) は指数バックオフ 1s/2s/4s・3 回再試行。
    - 成功レスポンスでも ``embedding.values`` の次元が EMBEDDING_DIM でなければ
      GeminiEmbeddingError (モデル側仕様変更の早期検知)。
    """

    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        key = api_key if api_key is not None else os.environ.get(EMBEDDING_API_ENV)
        if not key:
            raise GeminiEmbeddingError(
                f"環境変数 {EMBEDDING_API_ENV} が未設定です (Gemini embedding API に必須)。"
            )
        self._api_key = key
        # requests モジュール自体が post を持つため既定はモジュール直叩き。
        self._session: Any = session if session is not None else requests

    def _embed(self, text: str) -> list[float]:
        payload = {
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": EMBEDDING_DIM,
        }
        headers = {"x-goog-api-key": self._api_key}
        last_err: Exception | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                resp = self._session.post(
                    _EMBED_URL, json=payload, headers=headers, timeout=_TIMEOUT_S
                )
            except requests.RequestException as e:  # ネットワーク断も一時障害として再試行
                last_err = e
            else:
                if resp.status_code == 200:
                    return self._parse_values(resp)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = GeminiEmbeddingError(
                        f"Gemini embedContent {resp.status_code}: {str(resp.text)[:200]}"
                    )
                else:  # 4xx は再試行しても変わらないため即失敗
                    raise GeminiEmbeddingError(
                        f"Gemini embedContent failed {resp.status_code}: {str(resp.text)[:200]}"
                    )
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(2**attempt)  # 1s / 2s / 4s
        raise GeminiEmbeddingError(
            f"Gemini embedContent failed after {_RETRY_ATTEMPTS} attempts: {last_err}"
        ) from last_err

    def _parse_values(self, resp: Any) -> list[float]:
        try:
            values = resp.json()["embedding"]["values"]
        except (KeyError, TypeError, ValueError) as e:
            raise GeminiEmbeddingError(
                f"Gemini embedContent: unexpected response shape: {str(resp.text)[:200]}"
            ) from e
        if not isinstance(values, list) or len(values) != EMBEDDING_DIM:
            got = len(values) if isinstance(values, list) else type(values).__name__
            raise GeminiEmbeddingError(
                f"Gemini embedContent: embedding dim mismatch (expected {EMBEDDING_DIM}, got {got})"
            )
        return [float(v) for v in values]

    def embed_document(self, text: str) -> list[float]:
        """格納用 embedding。非対称指示は text 側に含める
        (``compose_search_text`` が ``DOCUMENT_PREFIX`` を接頭済み)。"""
        return self._embed(text)

    def embed_query(self, text: str) -> list[float]:
        """検索クエリ用 embedding (``QUERY_PREFIX`` を接頭)。"""
        return self._embed(QUERY_PREFIX + text)


@functools.lru_cache(maxsize=64)
def embed_query_cached(text: str) -> list[float]:
    """検索経路用のクエリ embedding キャッシュ (lru_cache 64 件)。

    検索 API は count + iter の 2 回同一クエリで距離計算するため、
    100-300ms の embed 呼びを 1 回に吸収する。戻り値はキャッシュ共有の
    list であるため呼び出し側で破壊的に変更しないこと。
    """
    return GeminiEmbeddingClient().embed_query(text)


def vector_literal(vec: list[float]) -> str:
    """pgvector テキスト入力形式 ``'[0.1,0.2,...]'`` を組む。

    ``format(v, '.17g')`` で float64 往復精度を保証する (pgvector は内部
    float4 だが、入力段での余分な丸め誤差を持ち込まない)。
    """
    return "[" + ",".join(format(float(v), ".17g") for v in vec) + "]"


def upsert_embedding(conn, property_id: int, search_text: str, vec: list[float]) -> None:
    """property_embeddings への 1 行 upsert (commit は呼び出し側管理)。

    embedding は :func:`vector_literal` の文字列を ``%s`` で渡す — psycopg は
    str を型未指定 (unknown) で送るため PG 側が列型 vector(3072) へ解釈する。
    """
    conn.execute(
        """
        INSERT INTO property_embeddings
            (property_id, model, dim, search_text, search_text_hash, embedding)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE SET
            model = EXCLUDED.model,
            dim = EXCLUDED.dim,
            search_text = EXCLUDED.search_text,
            search_text_hash = EXCLUDED.search_text_hash,
            embedding = EXCLUDED.embedding,
            embedded_at = now()
        """,
        (
            property_id,
            EMBEDDING_MODEL,
            EMBEDDING_DIM,
            search_text,
            search_text_hash(search_text),
            vector_literal(vec),
        ),
    )


def embedding_coverage(conn) -> dict:
    """可視物件の embedding カバー率集計 ``{"visible_total", "embedded"}``。

    可視 = p.is_active OR ショートリスト saved/hide/reject (:data:`_VISIBLE_PREDICATE`)。
    """
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS visible_total, COUNT(pe.property_id) AS embedded
        FROM properties p
        LEFT JOIN property_shortlists s ON s.property_id = p.id
        LEFT JOIN property_embeddings pe ON pe.property_id = p.id
        WHERE {_VISIBLE_PREDICATE}
        """
    ).fetchone()
    return {"visible_total": int(row["visible_total"]), "embedded": int(row["embedded"])}


def _placeholders(n: int) -> str:
    return ",".join("%s" for _ in range(n))


def visible_property_ids(conn, limit: int | None = None) -> list[int]:
    """embedding 対象の可視物件 id 昇順リスト (``limit`` は先頭 N 件)。"""
    sql = (
        "SELECT p.id FROM properties p "
        "LEFT JOIN property_shortlists s ON s.property_id = p.id "
        f"WHERE {_VISIBLE_PREDICATE} ORDER BY p.id"
    )
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))
    return [int(r["id"]) for r in conn.execute(sql, params)]


def compose_texts_for(conn, pids: list[int]) -> dict[int, tuple[str, str]]:
    """物件 id 群の現在の (search_text, hash) を 500 件チャンクで合成する。

    ``search_text`` は ``DOCUMENT_PREFIX`` 込み・``hash`` はその SHA256
    (:func:`search_text_hash`)。backfill (sync) と Batch API 経路の
    pending 判定・stale guard で同一の合成を共有する SSOT。
    """
    # queries/__init__ → buildings → store.embeddings の循環回避のため遅延 import
    # (チャンク幅・子テーブル SELECT の SSOT は queries/_common 流用)
    from store.queries._common import (
        _ACCESS_CHILD_SQL,
        _CAMPAIGN_CHILD_SQL,
        _FEATURES_CHILD_SQL,
        _PLAN_CHILD_SQL,
        _fetch_child_rows_by_property,
    )

    out: dict[int, tuple[str, str]] = {}
    for start in range(0, len(pids), _CANDIDATE_CHUNK):
        chunk = pids[start : start + _CANDIDATE_CHUNK]
        props = {
            int(r["id"]): dict(r)
            for r in conn.execute(
                f"SELECT * FROM properties WHERE id IN ({_placeholders(len(chunk))})", chunk
            )
        }
        features = _fetch_child_rows_by_property(conn, _FEATURES_CHILD_SQL, chunk)
        accesses = _fetch_child_rows_by_property(conn, _ACCESS_CHILD_SQL, chunk)
        plans = _fetch_child_rows_by_property(conn, _PLAN_CHILD_SQL, chunk)
        campaigns = _fetch_child_rows_by_property(conn, _CAMPAIGN_CHILD_SQL, chunk)
        for pid in chunk:
            if pid not in props:
                # submit→適用の間に物件が消失した場合を許容 (呼び出し側の
                # pending 判定・stale guard は「合成結果が無い pid」を missing
                # として扱う)。backfill は可視 id から始めるため通常通らない。
                continue
            text = compose_search_text(
                props[pid],
                [f["feature_name"] for f in features.get(pid, [])],
                accesses.get(pid, []),
                plans.get(pid, []),
                campaigns.get(pid, []),
            )
            out[pid] = (text, search_text_hash(text))
    return out


def backfill_embeddings(
    *,
    limit: int | None = None,
    dry_run: bool = False,
    client: GeminiEmbeddingClient | None = None,
    progress_every: int = 500,
) -> dict:
    """未カバー / hash 不一致の可視物件へ embedding を埋める sync 経路本体。

    Batch API 経路 (:mod:`store.embeddings_batch`・``--mode batch`` 既定) の
    フォールバック用に温存する小〜中件向けシリアル実装。物件ごとに 1 HTTP 呼び
    (レート制限に接触し得るため大量 pending では使わないこと)。

    対象 (id 昇順・``limit`` は先頭 N 件の処理上限):

    - ``property_embeddings`` 行なし or ``model != EMBEDDING_MODEL``、または
    - ``search_text_hash`` が現在の合成結果と不一致

    ``compose_texts_for`` で合成 → hash 比較 → 必要なら ``client.embed_document``
    → :func:`upsert_embedding`。1 件の例外で止まらず ``failed`` を加算する
    (API レベルの再試行は client 内・DB は 1 物件ごとに commit して進捗を残す)。

    ``dry_run=True`` では API 呼び・upsert を行わず pending 計上のみ。
    接続は関数内で ``store.pg.open_connection()`` を開く。
    ``client=None`` かつ ``dry_run=False`` の場合は :class:`GeminiEmbeddingClient`
    を生成する (GEMINI_API_KEY 必須)。

    戻り値::

        {"candidates": 走査した可視物件数, "pending": 再embeddingが必要だった数,
         "embedded": 成功数, "skipped_unchanged": hash一致で不要だった数,
         "failed": 失敗数, "dry_run": bool}
    """
    if client is None and not dry_run:
        client = GeminiEmbeddingClient()

    stats = {
        "candidates": 0,
        "pending": 0,
        "embedded": 0,
        "skipped_unchanged": 0,
        "failed": 0,
        "dry_run": bool(dry_run),
    }

    with open_connection() as conn:
        pids = visible_property_ids(conn, limit)
        stats["candidates"] = len(pids)

        processed = 0
        for start in range(0, len(pids), _CANDIDATE_CHUNK):
            chunk = pids[start : start + _CANDIDATE_CHUNK]
            composed = compose_texts_for(conn, chunk)
            existing = {
                int(r["property_id"]): r
                for r in conn.execute(
                    "SELECT property_id, model, search_text_hash FROM property_embeddings "
                    f"WHERE property_id IN ({_placeholders(len(chunk))})",
                    chunk,
                )
            }

            for pid in chunk:
                processed += 1
                text, digest = composed[pid]
                cur = existing.get(pid)
                if (
                    cur is not None
                    and cur["model"] == EMBEDDING_MODEL
                    and cur["search_text_hash"] == digest
                ):
                    stats["skipped_unchanged"] += 1
                else:
                    stats["pending"] += 1
                    if not dry_run:
                        try:
                            vec = client.embed_document(text)
                            upsert_embedding(conn, pid, text, vec)
                            conn.commit()  # 1 物件ごとに確定 (部分進捗を残す)
                            stats["embedded"] += 1
                        except Exception as e:  # noqa: BLE001 - 1 物件の失敗で全体を止めない
                            conn.rollback()  # 中断されたトランザクションを回復
                            stats["failed"] += 1
                            print(
                                f"  ! embedding failed property_id={pid}: {e}", file=sys.stderr
                            )
                if progress_every and processed % progress_every == 0:
                    print(f"  ... {processed}/{len(pids)} properties processed")

    return stats
