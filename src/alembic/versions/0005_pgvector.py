"""pgvector 導入: property_embeddings テーブル (PG移行 Phase 7a・E7)。

docs/sqlite-pg-migration-plan.md §4 Phase 7。

- CREATE EXTENSION vector(D6 イメージ postgresql-17-pgvector 同梱・未 INSTALL)
- property_embeddings: 部屋単位の意味検索 embedding の正本。
  embedding は vector(3072)(E7: gemini-embedding-2・フル次元)。
- HNSW インデックスは作成しない(計画の設計判断): 8k 行規模は seq scan
  での全件距離計算が数十 ms・recall 100%。物件数 5 万+ または検索レイテンシ
  問題化で 0006 として HNSW + hnsw.iterative_scan を追加する。

Revision ID: pgvector
Revises: timestamptz
Create Date: 2026-10-09

"""

from typing import Sequence, Union

from alembic import op

revision: str = "pgvector"
down_revision: Union[str, None] = "timestamptz"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE property_embeddings (
            property_id integer NOT NULL
                REFERENCES properties(id) ON DELETE CASCADE,
            model text NOT NULL,
            dim integer NOT NULL,
            search_text text NOT NULL,
            search_text_hash text NOT NULL,
            embedding vector(3072) NOT NULL,
            embedded_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT property_embeddings_pkey PRIMARY KEY (property_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS property_embeddings")
    # 拡張は他経路(pgvector 直接利用)がない前提だが、残しておいても害はない。
    # リビジョンの対称性のため落とす。
    op.execute("DROP EXTENSION IF EXISTS vector")
