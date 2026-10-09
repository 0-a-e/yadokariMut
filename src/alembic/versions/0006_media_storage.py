"""メディアストレージ: media_assets / media_variants + property_images 取得状態列 (M1)。

docs/media-storage-rustfs-plan.md §2.4(DBスキーマ)。

- media_assets: rustfs(S3互換)に保存した画像実体のメタデータ。sha256 で
  バイト完全一致の重複排除、dhash で近重複クラスタの代表を管理(§2.7)。
  object_key は内容アドレス(sha256/xx/yy/<hash>.<ext>)。thumb_key は
  派生サムネ(無効時 NULL)。
- media_variants: クラスタ代表に統合した既知バリアントの証跡(実体は保存しない)。
  sha256 → 代表 media_id の短絡に使う(§2.5)。
- property_images への 4 列追加: media_id(取得済み実体へのリンク)と
  fetch_status(pending|stored|failed|skipped) / fetch_error / fetched_at。
  既存行は fetch_status='pending' となり media-backfill の対象になる。
- このリビジョンは store/repository.py の property_images 差分同期とセット:
  現行の DELETE→全件再INSERT では再スクレイプのたびに取得状態列が消えるため。

Revision ID: media
Revises: pgvector
Create Date: 2026-10-09

"""

from typing import Sequence, Union

from alembic import op

revision: str = "media"
down_revision: Union[str, None] = "pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE media_assets (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            sha256      CHAR(64) NOT NULL UNIQUE,
            dhash       BIGINT,
            bucket      TEXT NOT NULL,
            object_key  TEXT NOT NULL,
            thumb_key   TEXT,
            mime_type   TEXT NOT NULL,
            size_bytes  BIGINT NOT NULL CHECK (size_bytes >= 0),
            width       INTEGER,
            height      INTEGER,
            stored_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_media_assets_object_key ON media_assets(object_key)"
    )
    op.execute(
        """
        CREATE TABLE media_variants (
            sha256      CHAR(64) PRIMARY KEY,
            media_id    BIGINT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
            width       INTEGER,
            height      INTEGER,
            size_bytes  BIGINT,
            source_url  TEXT,
            seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_media_variants_media ON media_variants(media_id)")
    op.execute(
        """
        ALTER TABLE property_images
            ADD COLUMN media_id     BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            ADD COLUMN fetch_status TEXT NOT NULL DEFAULT 'pending',
            ADD COLUMN fetch_error  TEXT,
            ADD COLUMN fetched_at   TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    # media_assets を参照する列(FK)を先に落とす(依存順)。
    op.execute(
        """
        ALTER TABLE property_images
            DROP COLUMN media_id,
            DROP COLUMN fetch_status,
            DROP COLUMN fetch_error,
            DROP COLUMN fetched_at
        """
    )
    op.execute("DROP TABLE IF EXISTS media_variants")
    op.execute("DROP TABLE IF EXISTS media_assets")
