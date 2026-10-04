#!/usr/bin/env bash
# tippecanoe をソースからビルドして scripts/ksj/.tools/ にインストールする.
#
# 使い方:
#   scripts/ksj/build_tippecanoe.sh
#   GIT_URL=https://github.com/mapbox/tippecanoe scripts/ksj/build_tippecanoe.sh
#
# 注意: 本家 mapbox/tippecanoe（v1.36.0系）は PMTiles 出力に対応していないため、
# 既定では PMTiles 出力を追加した Felt 系フォーク（felt/tippecanoe）をビルドする。
# 本家を使うと --output=*.pmtiles が MBTiles(SQLite) 中身のまま出力される。
#
# 前提: gcc / make / git / zlib.h / sqlite3.h（Arch Linux なら base-devel + zlib + sqlite）
# 成果物: scripts/ksj/.tools/bin/tippecanoe
#
# ビルドが 10 分で終わらない・失敗する場合は中断する。その際はディストリの
# パッケージを利用すること（Arch: sudo pacman -S tippecanoe / Debian/Ubuntu:
# sudo apt install tippecanoe）。PATH に入るので ksj.py はそのまま動作する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="$SCRIPT_DIR/.tools"
SRC_DIR="$TOOLS_DIR/tippecanoe-src"
PREFIX="$TOOLS_DIR"
BUILD_TIMEOUT="${BUILD_TIMEOUT:-600}"   # 秒。環境変数で変更可
GIT_URL="${GIT_URL:-https://github.com/felt/tippecanoe}"  # PMTiles 出力対応フォーク

log() { printf '[build_tippecanoe] %s\n' "$*"; }

fail_with_hint() {
  log "ビルドに失敗しました（$1）。"
  log "ディストリのパッケージを利用してください:"
  log "  Arch Linux        : sudo pacman -S tippecanoe"
  log "  Debian / Ubuntu   : sudo apt install tippecanoe"
  log "  Fedora            : sudo dnf install tippecanoe"
  log "パッケージ版は PATH 上にインストールされるため、ksj.py はそのまま動作します。"
  exit 1
}

# ---- 依存の確認 -----------------------------------------------------------
for cmd in git make gcc; do
  command -v "$cmd" >/dev/null 2>&1 || fail_with_hint "必要コマンド $cmd がありません"
done
for header in zlib.h sqlite3.h; do
  header_path="/usr/include/$header"
  [ -f "$header_path" ] || fail_with_hint "$header が見つかりません（Arch: sudo pacman -S zlib sqlite）"
done

mkdir -p "$TOOLS_DIR"

# ---- clone ----------------------------------------------------------------
if [ -d "$SRC_DIR/.git" ]; then
  log "既存のソースを使用: $SRC_DIR"
else
  log "clone: $GIT_URL -> $SRC_DIR"
  git clone --depth 1 "$GIT_URL" "$SRC_DIR" || fail_with_hint "clone 失敗"
fi

# ---- build & install ------------------------------------------------------
JOBS="$(nproc 2>/dev/null || echo 2)"
log "make -j$JOBS（タイムアウト ${BUILD_TIMEOUT}秒。長い場合は BUILD_TIMEOUT=1800 等で延長可）"
if ! timeout "$BUILD_TIMEOUT" make -C "$SRC_DIR" -j"$JOBS"; then
  rc=$?
  if [ "$rc" -eq 124 ]; then
    fail_with_hint "タイムアウト（${BUILD_TIMEOUT}秒）"
  else
    fail_with_hint "make 失敗 (exit $rc)"
  fi
fi

log "make install PREFIX=$PREFIX"
make -C "$SRC_DIR" install PREFIX="$PREFIX" || fail_with_hint "make install 失敗"

# ---- verify ---------------------------------------------------------------
BIN="$PREFIX/bin/tippecanoe"
[ -x "$BIN" ] || fail_with_hint "$BIN が生成されませんでした"
log "OK: $BIN"
"$BIN" --version
