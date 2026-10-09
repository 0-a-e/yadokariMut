# 単一 Dockerfile (--target 分割)。frontend の供給方式でターゲットを選ぶ。
#
# | ターゲット      | frontend/dist の供給元            | deploy.sh 対応            |
# |----------------|-----------------------------------|---------------------------|
# | final-remote   | Stage1 でリモート Docker 内 build | --frontend remote (既定)  |
# | final-prebuilt | ローカル pnpm build した dist     | --frontend local          |
#
# - compose は build.target: ${BUILD_TARGET:-final-remote} で選択
#   (deploy.sh が BUILD_TARGET=final-remote|final-prebuilt を渡す)
# - plain `docker build .` の既定ターゲットは最終 stage の final-remote
#   (= 旧「引数なしの Dockerfile」= remote ビルドと同じ挙動)
# - EXPOSE / ENV / CMD は runtime-base に1箇所のみ (両 final が継承)

# --- Stage 1: Build Frontend (final-remote でのみ使用) ---
FROM node:22-alpine AS frontend-builder
WORKDIR /frontend

# Install pnpm
RUN npm install -g pnpm

# Copy package files and install dependencies
COPY frontend/package.json frontend/pnpm-lock.yaml* frontend/pnpm-workspace.yaml* ./
RUN pnpm install --frozen-lockfile

# Copy frontend source and build
COPY frontend/ ./
RUN pnpm build

# --- 共通ランタイムベース (旧 Stage2 の frontend 供給より前) ---
FROM python:3.11-slim AS runtime-base
WORKDIR /app

# Install system dependencies (SQLite3 is needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and config
COPY src/ ./src/
COPY config.json .

# Checkpoint / 永続データ用ディレクトリ
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV YADOKARIMUT_CHECKPOINT_DB=/app/data/agent_checkpoints.db
ENV PYTHONPATH=/app/src
ENV TZ=Asia/Tokyo

# Expose port 8000 for FastAPI
EXPOSE 8000

# Run uvicorn server with increased keep-alive for SSE streaming
# (モジュール名はテストと同一のフラット名。PYTHONPATH=/app/src で解決)
CMD ["uvicorn", "web_server:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120", "--proxy-headers"]

# --- Target: final-prebuilt (deploy.sh --frontend local) ---
# ローカルでビルドし rsync された frontend/dist を利用 (build context 必須)
FROM runtime-base AS final-prebuilt
COPY frontend/dist ./frontend/dist

# --- Target: final-remote (デフォルト / deploy.sh --frontend remote) ---
# 最終 stage に置くことで plain `docker build` の既定ターゲットになる
FROM runtime-base AS final-remote
COPY --from=frontend-builder /frontend/dist ./frontend/dist
