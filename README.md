# YadokariMut

YadokariMut はマンスリーマンションを効率的に比較・探索するためのダッシュボード型 Web システムです。

**多ソース収集**、各種追加費用やキャンペーンを適用した **滞在期間ベースの実質総額**、比較ボード、LLM / MCP 連携を統合しています。

> **status:** 開発先端ベースのスナップショット（2026-10-10 時点）です。安定後はバージョンごとにスナップショットを反映します。 プルリク大歓迎です！</br>
> **データ層:** 物件 DB は **PostgreSQL**（PostGIS + pgvector イメージ）へ移行済みです。スキーマは **Alembic** で管理します。旧 SQLite 経路は削除済みです。

---

## スクリーンショット

### ホーム

![エクスプローラー画面](assets/screenshots/explorer-main.jpg)

### 地図レイヤ

![地図レイヤ](assets/screenshots/map-layers.jpg)

### 比較ボード

![比較ボード](assets/screenshots/comparison-board.jpg)

### 物件分析

![物件分析](assets/screenshots/analysis-modal.jpg)

物件単位の分析モーダル。滞在日数に応じた **実質 1 日単価のカーブ**（料金プラン）を中心に、価格推移や市場全体との相場比較を確認できます。

### 設定ボード

![設定ボード](assets/screenshots/admin-settings.jpg)

### モバイル（物件詳細）

![モバイル物件詳細](assets/screenshots/mobile-detail.jpg)

---

## 主な機能

### 1. インタラクティブ地図とリアルタイム探索

- **マップ連動ビュー**: Leaflet およびクラスタリング。地図の移動・ズームに合わせて表示物件が更新されます。
- **地図レイヤ**: 国土地理院の災害リスク情報（洪水浸水想定区域・土砂災害警戒区域・活断層図など）や標高・陰影図・衛星写真を重ねて表示。並べ替え・透明度・グループ化に対応し、既定構成はサーバー側（`/api/fe-settings`）に保存されます。
- **クライアントサイド高速フィルタ**: 都道府県、**データソース**、価格帯、間取り、築年数、最寄り駅徒歩分数、設備条件などを即座に絞り込み。大量データでも Web Worker により UI をブロックしません。
- **建物集約**: 同一建物の部屋（号室）を名寄せして建物単位で閲覧。地図ピン・詳細パネル・「まとめて非表示」・URL 状態（`?b=`）が建物単位で動作します。
- **部屋スペックの可視化**: 所在階・向き（角度）のパース結果を部屋カードに表示し、価格 / 階数 × 昇順・降順の並び替えに対応します。

### 2. 多ソース対応のデータ収集

- **SourceAdapter + Registry**: サイトごとに一覧・詳細の取得と正規化を実装（現状: **BraTTo** / **Union Monthly**）。
- **PostgreSQL 永続化**: 物件 DB は PostgreSQL（PostGIS + pgvector）。掲載 identity は `(source_site, external_id)`。スキーマは Alembic で管理します。
- **メディアストレージ**: 物件画像を S3 互換の **rustfs** に dhash による重複排除付きで保存（同梱 compose で rustfs を起動。未設定時はメディア機能のみ無効で起動）。
- **県ローテーション収集**: cron ごとに各都道府県を 1 バッチずつ順番に取得。日次上限・失敗バックオフ・飽和防止を備え、サイト負荷を抑えつつ全県を巡回します（`src/ingest/rotation.py`）。
- **設定ボード / API**: ソース別・都道府県単位の再取得、県ローテーションの進捗・実行ログ（`scrape_runs` / `scrape_run_targets`）を画面から確認できます。

### 3. 滞在期間ベースの実質総額シミュレータ

- **期間指定試算**: チェックイン / チェックアウトから契約帯（ショート・ミドル・ロング等）を `duration_*` で自動判定。
- **料金 SSOT**: バックエンドは `src/domain/pricing.py`（PricingEngine）。API は FE 互換のため `rent_plans` 形にもマップして返却。
- **キャンペーン**: 条件付き割引の構造化と、指定期間での有効性判定を反映した総額・日割り単価でソート可能。

### 4. ショートリストと比較ボード

- **検討中物件の保管**: 状態（検討中・非表示・見送り）とメモ。
- **掲載終了の可視化**: 非掲載になった物件はカードのバッジ・詳細のバナーで表示し、再掲載されれば自動で復帰します。
- **横並び比較**: 料金内訳、間取り、面積、設備、アクセスを一覧表示。

### 5. AI アシスタント & MCP

- **CopilotKit / AG-UI**: 画面チャットからフィルタ適用・比較・地図操作などを連動。
- **意味検索**: Gemini embedding × **pgvector** による自然文検索（「南向きでペット可の角部屋」等）に対応。ベクトルの生成は `backfill-embeddings` CLI（Gemini Batch API / sync フォールバック）。
- **MCP**: `src/cli.py run-mcp` で外部 LLM クライアントから検索・詳細・比較・建物・ショートリスト・GeoJSON 出力が可能。

### 6. URL 状態再現 & PWA

- **ディープリンク**: 期間・フィルタ・物件 ID・比較対象などが TanStack Router の search params に保持され共有可能。
- **モバイル / PWA**: 「ホーム」「地図」「AI」の下部タブと、リスト / レイヤの切り替えに対応。ホーム画面追加にも対応します。

---

## デプロイ(Docker Compose)

環境変数や API キーの詳細は後述の [共通セットアップ](#共通セットアップ) を参照してください。

```bash
cp .env.example .env
# DEEPSEEK_API_KEY と rustfs の鍵 (YADOKARIMUT_RUSTFS_ACCESS_KEY / SECRET_KEY) を設定
# （.env.example 参照。rustfs の鍵は openssl rand -hex 16 などで生成した任意の文字列で可）
mkdir -p data

docker compose up --build -d   # db (PostgreSQL) + rustfs + app が起動
docker compose logs -f
```

> **Note**: `DEEPSEEK_API_KEY` なしでも動くかもしれません(動作未確認)

| 項目 | 内容 |
|------|------|
| 公開ポート | `127.0.0.1:8000`（API + 静的 UI）。db は `127.0.0.1:5433`、rustfs は `127.0.0.1:9000` にループバック公開 |
| データ層 | **PostgreSQL**（PostGIS + pgvector イメージを `deploy/postgres/` からビルド）。`YADOKARIMUT_PG_*` で変更可 |
| メディア | rustfs（S3 互換）。app は鍵未設定でもメディア機能が無効になるだけで起動します |
| 永続化 | `./data`（PGDATA・rustfs データ・生 HTML・タイル等）, `./config.json`, `./.env` |
| 定期収集 | `ENABLE_SCHEDULER=true`（**県ローテーション**で cron ごとに各県を 1 バッチずつ取得）。収集設定は管理画面から変更 |

初回のスキーマ適用とデータ投入例（コンテナ内）:

```bash
docker compose exec yadokari-mut python3 src/cli.py db-init      # Alembic upgrade head
docker compose exec yadokari-mut python3 src/cli.py scrape --source unionmonthly --pref osaka --pages 1 --delay 2.0
```

アクセス: `http://127.0.0.1:8000/`  

---

## MCPとして利用

```bash
source .venv/bin/activate
python3 src/cli.py run-mcp
```

設定例（**本リポジトリの絶対パス**に置き換え）:

```json
{
  "mcpServers": {
    "yadokariMut-explorer": {
      "command": "/path/to/yadokariMut/.venv/bin/python3",
      "args": ["/path/to/yadokariMut/src/cli.py", "run-mcp"]
    }
  }
}
```

主なツールの例: `search_properties`, `get_property_detail`, `compare_properties`, `get_shortlist`, `export_map_data`

---

## 利用上の注意・免責事項

- 本ソフトウェアは **MIT License** で提供されます（`LICENSE` 参照）。
- 第三者サイトからのデータ取得機能が含まれます。**利用規約・robots.txt・関連法令を遵守し、自己責任で運用**してください。
- リポジトリに **物件 DB・生 HTML・取得成果物は同梱されていません**。各自で初期化・取得してください。

---

## 技術的詳細

### システムアーキテクチャ

```mermaid
graph TD
    subgraph Ingest ["データ収集パイプライン"]
        Config["config.json\nsources.*"] --> Registry["SourceRegistry\nsrc/sources/registry.py"]
        Registry --> Adapters["SourceAdapter\nbratto / unionmonthly / …"]
        Adapters --> Pipeline["IngestPipeline\nsrc/ingest/pipeline.py"]
        Pipeline --> Raw["raw_pages + HTML 保存"]
        Pipeline --> Repo["Repository\nsrc/store/repository.py"]
        Repo --> PG[("PostgreSQL\nPostGIS + pgvector")]
        Repo --> Media[("rustfs\nメディアストア")]
        PG --> Pricing["PricingEngine SSOT\nsrc/domain/pricing.py"]
        PG --> Geo["geocode_v2\nsrc/store/"]
        PG --> Campaign["campaign_structurer\nsrc/sources/bratto/"]
    end

    subgraph Server ["サーバー・配信層"]
        PG --> ApiQ["store/queries\n(FE 互換 rent_plans マップ)"]
        ApiQ --> API["FastAPI\nsrc/web/ (create_app + routers)"]
        API --> Agent["agent_service.py\nAG-UI"]
        API -.->|APScheduler\n県ローテーション収集| Pipeline
        CLI["CLI\nsrc/cli.py"] --> Pipeline
        MCP["MCP サーバー\nsrc/mcp_server.py"] --> ApiQ
    end

    subgraph Client ["クライアント層"]
        MCP -->|stdio| ExtLLM["外部 LLM"]
        API -->|REST / GeoJSON| ReactApp["React 18 + TypeScript"]
        ReactApp -->|AG-UI SSE| Agent
        ReactApp --> Worker["Web Worker\nfilter.worker.ts"]
    end

    style PG fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#fff
    style Pricing fill:#312e81,stroke:#a5b4fc,stroke-width:1px,color:#fff
    style ReactApp fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff
    style API fill:#1e293b,stroke:#854dff,stroke-width:2px,color:#fff
```

**データベース**: 物件ドメインは PostgreSQL（PostGIS + pgvector イメージ）。接続先は環境変数 `YADOKARIMUT_PG_DSN`（未設定時は compose 既定 `postgresql://yadokari:yadokari-mut@127.0.0.1:5433/property`）。

---

### データベース構造

スキーマの正本は **Alembic マイグレーション**（`src/alembic/versions/`、ベースライン `0001_pg_baseline` 以降）。`db-init` が `alembic upgrade head` 相当を適用します。

主要なテーブル構成（概要）:

```mermaid
erDiagram
    properties ||--o{ price_plans : "1:N 料金プラン"
    properties ||--o{ campaigns : "1:N キャンペーン"
    properties ||--o{ property_accesses : "1:N アクセス"
    properties ||--o{ property_images : "1:N 画像"
    properties ||--o{ property_links : "1:N リンク"
    properties ||--o{ property_features : "1:N 設備"
    properties ||--o{ property_snapshots : "1:N スナップショット"
    properties ||--o{ property_embeddings : "1:N 意味検索ベクトル"
    properties ||--o| property_shortlists : "1:0..1 検討状態"
    properties }o--o| buildings : "N:1 建物名寄せ"
    buildings ||--o{ building_names : "1:N 名称"
    buildings ||--o{ building_shortlists : "1:N 建物検討状態"
    scrape_runs ||--o{ scrape_run_targets : "1:N ターゲット"
```

#### 主要テーブル解説

- **`properties`**: 多ソース物件（部屋）の現在値。identity は `UNIQUE(source_site, external_id)`。検索用キャッシュ（`catalog_rent_per_day_yen`・階数 `floor_number`・向き `orientation_deg` 等）を保持。
- **`price_plans`**: 料金テーブル。帯判定は **`duration_min_days` / `duration_max_days`**。`presentation_unit` は `per_day` | `per_month`（月額は PricingEngine が 30 日換算で日額化）。プラン語彙は `plan_catalog`（`plan_label` 配信）。
- **`campaigns`**: 条件付き割引・特典。対象プランは **`target_plan_key`**。
- **`property_features`**: 設備。フィルタ用の正規化カテゴリ **`category`**（`feature_categories` 辞書で解決）を持つ。
- **`property_accesses` / `property_images` / `property_links`**: 交通・画像・外部リンク。
- **`property_snapshots`**: 取得時点の履歴（カタログ賃料など）。
- **`property_embeddings`**: 意味検索用の埋め込みベクトル（pgvector）。`embedded_sha256` で元テキストの差し替えを検知。
- **`buildings` / `building_names`**: 部屋の建物名寄せ結果（`building_identity` バッチ + 手動 merge/split CLI）。
- **`property_shortlists` / `building_shortlists`**: 物件 / 建物単位の検討状態（status + メモ）。
- **`media_assets` / `media_variants`**: rustfs に保存した画像と派生サイズ（dhash 重複排除）。
- **`scrape_runs` / `scrape_run_targets` / `rotation_state`**: ソース単位の実行、ターゲット単位の進捗、県ローテーション状態。
- **`raw_pages`**: 生 HTML メタデータ（再パース・差分用。物件への FK は持たない）。
- **`app_settings`**: 収集設定などの JSON 設定ストア（管理画面から編集）。

---

### データパイプラインと処理フロー

```text
[1. discover/list] → [2. detail parse] → [3. persist] → [4. enrich]
 SourceAdapter        Adapter + Domain      Repository         geocode / campaign
 config sources.*     models               price_plans 等      feature / score
        └──────── IngestPipeline (src/ingest/pipeline.py) ────────┘
                              ↓
              PricingEngine (読み取り時・検索時の stay / effective)
                              ↓
                    API / MCP / GeoJSON / Frontend
```

1. **一覧・詳細収集 (`scrape` / `IngestPipeline`)**  
   - `config.json` の `sources.<id>` と `SourceRegistry` で Adapter を起動。  
   - 一覧ページング → 詳細 HTML 取得 → Domain DTO へ正規化 → `Repository` で upsert。  
   - 生 HTML は `raw_pages` / ストレージに保存可能（`--no-raw` で省略可）。
2. **永続化 (`src/store/`)**  
   - DDL 正本は Alembic（`src/alembic/`）。読み取り API 形への変換は `store/queries/`（search / detail / price_history / buildings / geojson / export。`price_plans` → FE 互換 `rent_plans`）。
3. **料金計算 (`src/domain/pricing.py`)**  
   - stay 日数 inclusive、帯は duration マッチ、月額は `MONTH_DAYS=30` で日額化。  
   - 総額 ≈ (賃料日額 + 管理日額 + 光熱日額*) × 日数 + 清掃 + 契約手数料。
4. **ジオコーディング**  
   - `store/geocode_v2.py` 等。住所 → lat/lng（Nominatim / Google 等）。
5. **キャンペーン**  
   - 構造化は `src/sources/bratto/campaign_structurer.py`。指定期間での有効割引の反映は `domain/pricing.py`。

CLI 対応表:

| 目的 | コマンド |
|------|----------|
| スキーマ適用 (Alembic upgrade head) | `python3 src/cli.py db-init` |
| 多ソース収集 | `python3 src/cli.py scrape --source unionmonthly --pref osaka --pages 1` |
| 意味検索ベクトル生成 | `python3 src/cli.py backfill-embeddings`（`--dry-run` で対象件数確認） |
| 物件画像のメディア投入 | `python3 src/cli.py media-backfill` |
| 建物名寄せ | `python3 src/cli.py building-identity --dry-run` |
| 座標欠損のジオコード | `python3 src/cli.py geocode --limit 50` |

---

### 技術スタック一覧

| 領域 | 技術・ライブラリ | 概要・用途 |
|------|------------------|------------|
| **Back-end Core** | Python 3.10+, PostgreSQL 17（PostGIS + pgvector） | 言語基盤・物件 DB |
| **Schema Mgmt** | Alembic | DDL 移行の正本（`db-init`） |
| **Ingest** | SourceAdapter / Registry / IngestPipeline | 多ソース収集・正規化 |
| **Domain** | `domain/pricing.py`, `domain/models.py`, `domain/building_identity.py` | 料金・DTO・建物名寄せの SSOT |
| **Store** | `store/pg.py`, `repository.py`, `store/queries/` | 接続・永続化・読取 |
| **Media** | rustfs（S3 互換）+ dhash | 物件画像の重複排除付き保存 |
| **Web Server API** | FastAPI, Uvicorn, Pydantic | REST / GeoJSON / Admin / AG-UI |
| **Agent / AI** | CopilotKit v2, AG-UI Protocol | UI 連動エージェント |
| **LLM Integration** | MCP | 外部 LLM ツール |
| **Semantic Search** | Gemini embedding × pgvector | 自然文による物件検索 |
| **Task Schedule** | APScheduler | 定期 scrape（Compose 既定） |
| **Front-end Core** | React 18, TypeScript, Vite, **pnpm** | UI |
| **Routing / State** | TanStack Router | URL search 同期 |
| **Map & Visual** | Leaflet, MarkerCluster | 地図 |
| **UI** | Tailwind CSS, shadcn/ui / hextaUI, Lucide | コンポーネント |
| **Performance** | Web Worker (`filter.worker.ts`) | 大量フィルタ |

---

### ディレクトリ・モジュール構造

```text
yadokariMut/
├── pyproject.toml             pytest 設定 (testpaths=tests, pythonpath=src)
├── config.json                sources.* を含む設定
├── Dockerfile / docker-compose.yml
├── requirements.txt
├── .env.example
├── scripts/                   ユーティリティ
│   ├── export_openapi.py      OpenAPI スキーマ出力
│   ├── ksj/                   国土数値情報 → PMTiles 変換 (/api/tiles 用)
│   ├── migrations/            one-shot データ移行
│   └── rotation_sim.py        県ローテーション シミュレータ
├── tests/                     pytest スイート (実サイト fixtures は非同梱・該当テストは skip)
├── src/
│   ├── cli.py                 db-init / scrape / backfill-embeddings / media-backfill / building-identity / geocode / run-mcp 等
│   ├── mcp_server.py          MCP サーバー
│   ├── web_server.py          FastAPI 起動シム (uvicorn web_server:app)
│   ├── web/                   FastAPI 本体
│   │   ├── app.py             create_app + ルータ登録
│   │   └── routers/           properties / buildings / geojson / analysis / media / admin / …
│   ├── alembic/               スキーマ移行の正本 (alembic.ini + versions/)
│   ├── store/                 ★ データ層 (PostgreSQL)
│   │   ├── pg.py              接続 (DSN 解決・プール) + sqlite3.Row 互換行
│   │   ├── migrations.py      Alembic ラッパ (db-init)
│   │   ├── repository.py      永続化
│   │   ├── queries/           読取 (search / detail / buildings / price_history / geojson / …)
│   │   ├── embeddings.py / embeddings_batch.py
│   │   │                      意味検索ベクトル (sync / Gemini Batch API)
│   │   ├── media.py           rustfs メディアストア (dhash 重複排除)
│   │   ├── building_identity.py 建物名寄せ
│   │   ├── app_settings.py    収集設定などの JSON 設定ストア
│   │   ├── source_catalog.py  ソース一覧・管理 API 用
│   │   └── geocode_v2.py
│   ├── sources/               ★ サイト別 Adapter
│   │   ├── base.py / registry.py / parsing.py
│   │   ├── bratto/            一覧・詳細・正規化 (campaign_structurer 含む)
│   │   ├── unionmonthly/
│   │   └── http/              取得 HTTP・プロキシ骨格
│   ├── ingest/
│   │   ├── pipeline.py        list→detail→upsert オーケストレーション
│   │   ├── rotation.py        県ローテーション収集 (日次上限・失敗バックオフ)
│   │   └── raw_store.py
│   ├── domain/
│   │   ├── pricing.py         料金 SSOT
│   │   ├── models.py
│   │   ├── building_identity.py / embedding_text.py
│   │   ├── feature_categories.py / feature_resolution.py
│   │   └── plan_catalog.py    プラン表示語彙の SSOT
│   ├── agent_service.py       画面内 AI (AG-UI)
│   ├── api_models.py          OpenAPI 正本モデル
│   ├── fe_settings.py         フロント既定設定（レイヤ構成など）の保存 API
│   ├── tiles.py               PMTiles → ZXY 配信 (/api/tiles)
│   └── chat_threads.py
└── frontend/
    ├── src/
    │   ├── main.tsx           エントリ (Router + CopilotKit)
    │   ├── App.tsx            地図・サイドバー・詳細・比較の統合 UI
    │   ├── router.tsx / routes/
    │   ├── components/        feature 単位 (map / layers / sidebar / detail / analysis / chat / admin)
    │   ├── lib/               filterLogic / rentCalculator / api (openapi 生成型) / layers 等
    │   ├── hooks/             useMapActions / useFilteredFeatures / useCopilotContext 等
    │   └── workers/filter.worker.ts
    └── package.json
```

---

## 共通セットアップ

[デプロイ](#デプロイ)・[ローカル開発](#ローカル開発手順) 共通のセットアップです。

### 前提条件

| 用途 | 要件 |
|------|------|
| バックエンド | **Python 3.10+**（作業は必ず仮想環境 `.venv` 内） |
| フロント | **Node.js 18+**、パッケージ管理は **pnpm** |
| デプロイ | Docker / Docker Compose（[デプロイ](#デプロイ) 節） |

### リポジトリ取得と設定ファイル

```bash
git clone https://github.com/0-a-e/yadokariMut
cd yadokariMut
cp .env.example .env
```

スクレイプ対象・ソース有効化などは **`config.json`**（リポジトリ同梱）を編集します。API キーは `config.json` ではなく **`.env`** に書いてください。

### 環境変数・API キー一覧

テンプレート:  **`.env.example`**

#### データベース (PostgreSQL)

| 変数 | 既定 | 説明 |
|------|------|------|
| `YADOKARIMUT_PG_USER` / `YADOKARIMUT_PG_PASSWORD` / `YADOKARIMUT_PG_DB` | `yadokari` / `yadokari-mut` / `property` | compose db サービスの認証情報。app コンテナ内の DSN もここから組み立て |
| `YADOKARIMUT_PG_DSN` | （compose 内で自動設定） | app が接続する DSN。ホスト実行時の未設定時は `postgresql://yadokari:yadokari-mut@127.0.0.1:5433/property` |
| `YADOKARIMUT_PG_PORT` | `5433` | db サービスのホスト側ポート（ループバックのみ） |
| `YADOKARIMUT_PGDATA_DIR` | `./data/postgres-property` | PGDATA の配置先（任意ディレクトリへ外出し可） |

#### API キー

| 変数 | 役割 | 説明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | 推奨 | [DeepSeek](https://platform.deepseek.com/) の API キー。画面内 AI チャット機能やキャンペーン・設備の LLM 分類で使用。無くても動くかもだが動作未確認 |
| `GEMINI_API_KEY` | 意味検索を使う場合 | Gemini embedding による意味検索（pgvector）のベクトル生成で使用。`backfill-embeddings` CLI でバックフィル |
| `GOOGLE_MAPS_API_KEY` | Google ジオコード時 | 未設定時は Nominatim 経路のみで動作 |
| `DEEPSEEK_BASE_URL` | 任意 | 既定 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 任意 | 既定 `deepseek-flash` |

#### メディアストレージ (rustfs)

| 変数 | 必須? | 説明 |
|------|--------|------|
| `YADOKARIMUT_RUSTFS_ACCESS_KEY` / `YADOKARIMUT_RUSTFS_SECRET_KEY` | compose 起動に必須 | rustfs サービスの認証情報。値は任意（`openssl rand -hex 16` 等で生成）。app へ未設定のままでもメディア機能が無効になるだけで起動します |
| `YADOKARIMUT_RUSTFS_BUCKET` | 任意 | 既定 `yadokari-media` |
| `YADOKARIMUT_RUSTFS_DATA_DIR` | 任意 | 既定 `./data/rustfs` |


```bash
# .env の例（値は自分のキーに置き換え）
...
DEEPSEEK_API_KEY=...
# Google ジオコードを使う場合
# GOOGLE_MAPS_API_KEY=...
...
```

#### 運用・収集まわり（任意）

収集の実行設定（県ローテーションの cron・日次上限・失敗バックオフ等）は **管理画面（設定ボード）から変更し、DB 上の `app_settings` に保存**されます。環境変数では管理しません。

| 変数 | 既定の目安 | 説明 |
|------|------------|------|
| `ENABLE_SCHEDULER` | Compose: `true` / ローカル: 未設定なら off | `true` で APScheduler を起動 |
| `TILES_DIR` | `data/tiles` | `scripts/ksj/` で生成した PMTiles の配置先（`/api/tiles/{code}/{z}/{x}/{y}.pbf` 配信） |
| `YADOKARIMUT_CHECKPOINT_DB` | `data/agent_checkpoints.db` 相当 | エージェント／チャットスレッド用 SQLite |
| `SCRAPE_HTTP_MODE` | `off` | 収集 HTTP: `off` / `fallback` / `always_proxy` |
| `SCRAPE_HTTP_PROXY` | （なし） | プロキシ URL（`fallback` / `always_proxy` 時） |
| `SCRAPE_HTTP_MAX_RETRIES` | `2` | 取得リトライ回数 |
| `SCRAPE_HTTP_TIMEOUT_SECONDS` | `45` | タイムアウト秒 |
| `SCRAPE_PROXY_COOLDOWN_SECONDS` | `600` | プロキシ冷却秒 |

---

## ローカル開発手順

### 1. Python 環境と PostgreSQL

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 物件 DB 用 PostgreSQL を起動 (compose の db サービス。ホストの 127.0.0.1:5433 で待受)
docker compose up -d db

# スキーマ適用 (Alembic upgrade head)
python3 src/cli.py db-init
```

接続先は `YADOKARIMUT_PG_DSN` で変更できます（未設定時は `postgresql://yadokari:yadokari-mut@127.0.0.1:5433/property`）。rustfs を含む全体を起動する場合は `docker compose up -d` を使用してください。

### 2. データ投入

リポジトリに物件データは含まれません。Frontendから操作するか、以下のコマンドで取得できます。

```bash
# Union Monthly（--source 省略時のデフォルトは unionmonthly）
python3 src/cli.py scrape --source unionmonthly --pref osaka --pages 1 --delay 2.0

# BraTTo
python3 src/cli.py scrape --source bratto --pref osaka --pages 1 --delay 1.5

# よく使うオプション
#   --all-pages      一覧を最後まで
#   --list-only      詳細を取らない
#   --max-details N  詳細件数上限
#   --mark-inactive  今回見えなかった ID を inactive
```

座標が空の物件がある場合:

```bash
python3 src/cli.py geocode --limit 50
```

### 3. 開発サーバー（API + フロント）

**ターミナル 1 — FastAPI（`:8000`）**

```bash
source .venv/bin/activate
uvicorn web_server:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

**ターミナル 2 — Vite（`:5173`）**

```bash
cd frontend
pnpm install
pnpm dev
```

- UI: `http://localhost:5173/`
- `/api` は Vite プロキシ経由で `localhost:8000` へ転送

---

## テストの実行

> **Note**: バックエンドのテストスイートは `tests/` 配下にあります（`pyproject.toml` の設定で収集）。**テストは PostgreSQL を使用します**（テンプレート DB からの複製で隔離するため、事前に `docker compose up -d db` を実行してください）。実サイトのスクレイプ HTML フィクスチャ（`tests/fixtures/`）はリポジトリに同梱していないため、該当テストは自動的に skip されます。フロントの生成型を検証するテストも node / pnpm 環境が無い場合に skip されます。

### バックエンド

```bash
source .venv/bin/activate
pip install pytest
pytest
```

### フロントエンド

```bash
cd frontend
pnpm test
pnpm exec tsc --noEmit
```

---

## 謝辞

複数ソース対応に当たって[notLukeshi/apt-finder](https://github.com/notLukeshi/apt-finder)を参考にさせて頂きました。この場を借りて感謝申し上げます。

---

## ライセンス

[MIT License](LICENSE)
