# PostGIS + pgvector の最小構成イメージ(物件ドメイン PostgreSQL)。
# 空間ドメイン PoC (feat/pg-spatial scripts/osm/Dockerfile.postgres) と同一構成・
# 同一イメージタグを共用する(docs/sqlite-pg-migration-plan.md D6/E1)。
# 素体 imresamu/postgis(PostGISのみ)に、Debian本家パッケージのpgvectorを追加する。
# pgvectorは当面未使用でも CREATE EXTENSION vector 可能な状態にしておく(Phase 7)。
FROM imresamu/postgis:17-3.6

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-17-pgvector \
 && rm -rf /var/lib/apt/lists/*
