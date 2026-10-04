#!/usr/bin/env python3
"""国土数値情報（KSJ）GML ダウンロード & PMTiles 変換パイプライン.

標準ライブラリのみで動作する単一 CLI。外部コマンドは変換時のみ使用する:
  - GML -> GeoJSON : ogr2ogr（無ければ venv 内の pip install gdal / osgeo.ogr）
  - GeoJSON -> PMTiles : tippecanoe（無ければ build_tippecanoe.sh で .tools/ にビルド）

サブコマンド:
  catalog                       データセット一覧を取得して JSON 出力
  files CODE [--pref][--year]   ダウンロード可能ファイル一覧（実URLの解決）
  download CODE [--pref][--year][--dry-run]  zip を data/raw/CODE/ へ取得（レジューム対応）
  convert CODE [--force]        zip 解凍 -> GeoJSON -> PMTiles（各段階冪等）

データの出典・ライセンスは refs/ksj/README.md を参照。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

BASE_URL = "https://nlftp.mlit.go.jp/ksj/"
CATALOG_URL = urljoin(BASE_URL, "gml/gml_datalist.html")
USER_AGENT = "yadokariMut-ksj-pipeline/0.1 (personal use; python-urllib)"

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
DATALIST_CACHE_DIR = CACHE_DIR / "datalist"
RAW_DIR = DATA_DIR / "raw"
GEOJSON_DIR = DATA_DIR / "geojson"
PMTILES_DIR = DATA_DIR / "pmtiles"
TOOLS_DIR = SCRIPT_DIR / ".tools"

CACHE_TTL_SEC = 24 * 3600  # HTML キャッシュの有効期限
REQUEST_INTERVAL_SEC = 2.0  # リクエスト間の間隔（サーバ負荷配慮）
DOWNLOAD_CHUNK = 256 * 1024

_last_request_time = 0.0


# --------------------------------------------------------------------------
# HTTP / キャッシュ
# --------------------------------------------------------------------------
def _throttle() -> None:
    global _last_request_time
    wait = REQUEST_INTERVAL_SEC - (time.monotonic() - _last_request_time)
    if wait > 0:
        time.sleep(wait)
    _last_request_time = time.monotonic()


def _fetch(url: str, cache_path: Path | None = None, refresh: bool = False) -> str:
    """GET してテキストを返す。cache_path があれば TTL 付きディスクキャッシュを使う。"""
    if cache_path is not None and not refresh and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < CACHE_TTL_SEC:
            return cache_path.read_text(encoding="utf-8")
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {url}\n（ページが存在しない／一時的な障害の可能性があります）") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"接続エラー: {url}\n{e.reason}") from e
    text = data.decode("utf-8", errors="replace")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------
# HTML パース（正規表現ベース・標準ライブラリのみ）
# --------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TEMPLATE_HREF_RE = re.compile(r'href="(/ksj/gml/datalist/KsjTmplt-[A-Za-z0-9_-]+?\.html)"')


def _clean(fragment: str) -> str:
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub("", fragment))).strip()


def _code_of(template: str) -> str:
    """KsjTmplt- のテンプレート名からデータセットコードを取り出す（年度サフィックスを除去）.

    例: 'N03-2026' -> 'N03', 'A55-2024' -> 'A55', 'A18s-a' -> 'A18s-a', 'mesh250r6' -> 'mesh250r6'
    """
    return re.sub(r"-\d{4}$", "", template)


def parse_catalog(html: str) -> list[dict]:
    """gml_datalist.html をパースしてデータセット一覧を返す.

    refs/ksj/ksj_datasets.json と同等の形式（cat / code / name / lic / agr / unit）。
    """
    entries: list[dict] = []
    sections = re.split(
        r'<div class="collapsible-header[^"]*">\s*<p class="white-text">', html
    )
    for sec in sections[1:]:
        header = sec.split("</p>", 1)[0]
        header = re.sub(r"<i[^>]*>.*?</i>", "", header, flags=re.S)  # arrow_drop_down 等
        cat = _clean(header)
        for row in re.findall(r"<tr>(.*?)</tr>", sec, re.S):
            m = _TEMPLATE_HREF_RE.search(row)
            if not m:
                continue  # 【水域】等の見出し行
            code = _code_of(m.group(1).removeprefix("/ksj/gml/datalist/KsjTmplt-").removesuffix(".html"))
            name_m = re.search(r'KsjTmplt-[A-Za-z0-9_-]+?\.html"[^>]*>([^<]+)</a>', row)
            name = _clean(name_m.group(1)) if name_m else ""
            lic = agr = ""
            lm = re.search(r'agreement_(\d+)\.html"[^>]*>\s*([^<]*?)\s*</a>', row)
            if lm:
                agr, lic = lm.group(1), _clean(lm.group(2))
            unit = ""
            # refs/ksj/ksj_datasets.json の unit は「位置正確度」列（2番目の中央寄せセル）。
            ums = re.findall(r'<td align="center">(.*?)</td>', row, re.S)
            if len(ums) >= 2:
                unit = _clean(ums[1])
            entries.append(
                {"cat": cat, "code": code, "name": name, "lic": lic, "agr": agr, "unit": unit}
            )
    return entries


def load_catalog(refresh: bool = False) -> list[dict]:
    cache = CACHE_DIR / "catalog.json"
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL_SEC:
        return json.loads(cache.read_text(encoding="utf-8"))
    html = _fetch(CATALOG_URL, CACHE_DIR / "catalog.html", refresh=refresh)
    entries = parse_catalog(html)
    if not entries:
        raise SystemExit("カタログのパースに失敗しました（サイト構造が変わった可能性があります）")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    return entries


def _template_url_for(code: str) -> str:
    """データセットコード -> ダウンロードページ（KsjTmplt-*.html）の URL.

    カタログに載っているページURLを優先する（N03-2026 / A55-2024 等の年度入りや
    コンテナページはカタログのリンクが正）。無ければ KsjTmplt-<code>.html を推定。
    """
    html = _fetch(CATALOG_URL, CACHE_DIR / "catalog.html")
    for m in _TEMPLATE_HREF_RE.finditer(html):
        if _code_of(Path(m.group(1)).stem.removeprefix("KsjTmplt-")) == code:
            return urljoin(CATALOG_URL, m.group(1))
    return urljoin(BASE_URL, f"gml/datalist/KsjTmplt-{code}.html")


_ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925, "大正": 1911, "明治": 1867}


def _years_in_text(text: str) -> set[int]:
    """年セルのテキスト（例: '2024年（令和6年）', '平成23年'）から西暦年を取り出す。"""
    years = {int(y) for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", text)}
    for era, base in _ERA_BASE.items():
        for m in re.finditer(era + r"(\d+)", text):
            years.add(base + int(m.group(1)))
    return years


def parse_datalist(html: str, page_url: str, owner_code: str) -> tuple[list[dict], list[str]]:
    """ダウンロードページをパースして (ファイル一覧, 下位データセットコード一覧) を返す.

    DownLd('サイズ','ファイル名','相対パス' ,this) の第3引数 + ページURL から実URLを解決する。
    テーブルを持たない「コンテナページ」(README §2.2, A55 等) では files=空、
    children に下位データセットコードを返す。
    """
    files: list[dict] = []
    children: list[str] = []
    for m in _TEMPLATE_HREF_RE.finditer(html):
        child = _code_of(Path(m.group(1)).stem.removeprefix("KsjTmplt-"))
        if child != owner_code and child not in children:
            children.append(child)
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        dm = re.search(r"DownLd\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'", row)
        if not dm:
            continue
        size, filename, rel = (unescape(g).strip() for g in dm.groups())
        url = urljoin(page_url, rel)
        pref_id = pref_name = ""
        pm = re.search(r'id="prefecture(\d\d)"', row)
        if pm:
            pref_id = pm.group(1)
            name_m = re.search(r'id="prefecture\d\d"[^>]*>([^<]*)</td>', row)
            if name_m:
                pref_name = _clean(name_m.group(1))
        datum = year_text = ""
        for td in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S):
            text = _clean(td)
            if "測地系" in text and not datum:
                datum = text
            elif not year_text and _years_in_text(text):
                year_text = text
        files.append(
            {
                "code": owner_code,
                "pref": pref_id,
                "pref_name": pref_name,
                "datum": datum,
                "year": year_text,
                "size": size,
                "filename": filename,
                "url": url,
            }
        )
    return files, children


def resolve_files(
    code: str, pref: str | None = None, year: int | None = None,
    refresh: bool = False, follow_children: bool = True,
) -> tuple[list[dict], list[str]]:
    """CODE のダウンロードページを解決し、フィルタ済みファイル一覧を返す.

    戻り値は (ファイル一覧, 辿ったコード一覧)。コンテナページ (A55 等) の場合は
    follow_children=True なら下位コードのページも取得してマージする。
    """
    page_url = _template_url_for(code)
    html = _fetch(page_url, DATALIST_CACHE_DIR / Path(page_url).name, refresh=refresh)
    files, children = parse_datalist(html, page_url, code)
    visited = [code]
    if not files and children and follow_children:
        for child in children:
            child_url = _template_url_for(child)
            child_html = _fetch(
                child_url, DATALIST_CACHE_DIR / Path(child_url).name, refresh=refresh
            )
            child_files, _ = parse_datalist(child_html, child_url, child)
            files.extend(child_files)
            visited.append(child)
    if pref:
        files = [f for f in files if f["pref"] == pref.zfill(2)]
    if year:
        files = [f for f in files if year in _years_in_text(f["year"])]
    return files, visited


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------
def _human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)}B" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def download_file(url: str, dest: Path) -> Path:
    """Range リクエストでレジューム対応ダウンロード（.part 完了後にリネーム）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(url, headers=headers)
    _throttle()
    try:
        resp = urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        if e.code == 416 and offset:  # 全量取得済み
            part.rename(dest)
            return dest
        raise SystemExit(f"HTTP {e.code}: {url}") from e
    resume = resp.status == 206 and offset > 0
    mode = "ab" if resume else "wb"
    length = resp.getheader("Content-Length")
    total = int(length) + offset if (length and resume) else (int(length) if length else None)
    done = offset if resume else 0
    try:
        with part.open(mode) as f:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                prev_mb, done = done, done + len(chunk)
                if total and done // (10 * 1024 * 1024) != prev_mb // (10 * 1024 * 1024):
                    pct = f" ({done * 100 // total}%)" if total else ""
                    print(f"  {_human_size(done)}{pct}", flush=True)
    finally:
        resp.close()
    if total and done < total:
        raise SystemExit(
            f"ダウンロードが途中で終了しました: {url} ({done}/{total}B)\n再実行するとレジュームします。"
        )
    part.rename(dest)
    return dest


def cmd_download(args: argparse.Namespace) -> None:
    files, _ = resolve_files(args.code, args.pref, args.year, refresh=args.refresh)
    if not files:
        raise SystemExit(f"該当ファイルがありません: code={args.code} pref={args.pref} year={args.year}")
    for f in files:
        dest = RAW_DIR / args.code / f["filename"]
        if args.dry_run:
            print(f"{f['url']}\n  -> {dest}  ({f['size']}, {f['pref_name'] or '全国'} {f['year']})")
            continue
        if dest.exists():
            print(f"スキップ（既存）: {dest}")
            continue
        print(f"ダウンロード: {f['url']}")
        download_file(f["url"], dest)
        print(f"  -> {dest} ({_human_size(dest.stat().st_size)})")
    if args.dry_run:
        print(f"\n{len(files)} 件（dry-run: ダウンロードしていません）")


# --------------------------------------------------------------------------
# convert: zip 解凍 -> GML -> GeoJSON -> PMTiles
# --------------------------------------------------------------------------
def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    resolved_root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(resolved_root)):
                raise SystemExit(f"zip 内の不正なパスを検出: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _extract_zips(code: str) -> list[Path]:
    """data/raw/CODE/*.zip を解凍し、変換対象ファイル一覧を返す（冪等）。"""
    raw = RAW_DIR / code
    zips = sorted(raw.glob("*.zip"))
    if not zips:
        raise SystemExit(
            f"zip がありません: {raw}\n先に `ksj.py download {code}` を実行してください。"
        )
    data_files: list[Path] = []
    for zp in zips:
        dest = raw / "extracted" / zp.stem
        if not dest.exists() or not any(dest.iterdir()):
            print(f"解凍: {zp.name} -> {dest.relative_to(SCRIPT_DIR)}")
            _safe_extract(zp, dest)
        else:
            print(f"スキップ（解凍済み）: {zp.name}")
        found = [
            p for p in sorted(dest.rglob("*"))
            if not p.name.startswith("KS-META-")  # ISOメタデータ（地理データではない）
            and p.suffix.lower() in (".xml", ".gml", ".shp", ".geojson")
        ]
        if not found:
            print(f"警告: {zp.name} に変換可能なファイルがありません")
        data_files.extend(found)
    return data_files


def _find_ogr2ogr() -> str | None:
    found = shutil.which("ogr2ogr")
    if found:
        return found
    local = TOOLS_DIR / "bin" / "ogr2ogr"
    return str(local) if local.exists() else None


def _find_tippecanoe() -> str | None:
    found = shutil.which("tippecanoe")
    if found:
        return found
    local = TOOLS_DIR / "bin" / "tippecanoe"
    return str(local) if local.exists() else None


def _ensure_gdal_hint() -> None:
    print(
        "GML を読める変換器がありません。次のいずれかを用意してください:\n"
        "  1) ogr2ogr をインストール（例: sudo pacman -S gdal）\n"
        "  2) 本スクリプト用 venv に pip install gdal\n"
        "     python3 -m venv scripts/ksj/.venv && scripts/ksj/.venv/bin/pip install gdal\n"
        "詳細は scripts/ksj/README.md を参照。",
        file=sys.stderr,
    )


def _srs_of(gml: Path) -> tuple[str | None, bool]:
    """GML の srsName 宣言から (EPSGコード or None, 旧日本測地系か) を推定する.

    KSJ の現行データは世界測地系（JGD2011 = EPSG:6668 / JGD2000 = EPSG:4612 と宣言される）。
    None は宣言が読み取れなかった意味で、呼び出し側が EPSG:4612 を仮定する。
    旧日本測地系（東京測地系）は EPSG:4301 / 'tokyo' で検出する。
    """
    try:
        head = gml.read_bytes()[:65536].decode("utf-8", errors="replace")
    except OSError:
        head = ""
    declared: str | None = None
    legacy = False
    for m in re.finditer(r'srsName="([^"]+)"', head):
        s = m.group(1)
        dm = re.search(r"(\d{4})", s)
        if dm and declared is None:
            declared = f"EPSG:{dm.group(1)}"
        if "4301" in s or "tokyo" in s.lower():
            legacy = True
    return declared, legacy


def _convert_with_ogr2ogr(ogr: str, gml: Path, out_base: Path) -> list[Path]:
    """ogr2ogr で GML/Shape -> GeoJSON (WGS84)。マルチレイヤはレイヤ毎に分岐。"""
    declared, legacy = _srs_of(gml)
    if legacy:
        print(f"  注意: {gml.name} は旧日本測地系の可能性があります（宣言に従い WGS84 へ変換）。")
    layers: list[str | None]
    ogrinfo = shutil.which("ogrinfo") or str(TOOLS_DIR / "bin" / "ogrinfo")
    if Path(ogrinfo).exists():
        r = subprocess.run([ogrinfo, "-q", "-so", str(gml)], capture_output=True, text=True)
        if r.returncode == 0:
            layers = re.findall(r"^\d+: (.+?)(?: \([^)]*\))?$", r.stdout, re.M) or [None]
        else:
            layers = [None]
    else:
        layers = [None]
    outs: list[Path] = []
    for layer in layers:
        out = out_base if layer is None else out_base.with_name(f"{out_base.stem}__{layer}.geojson")
        if out.exists():
            outs.append(out)
            continue
        cmd = [ogr, "-f", "GeoJSON", "-t_srs", "EPSG:4326", "-lco", "COORDINATE_PRECISION=7"]
        if declared:  # GML の宣言に任せる（JGD2011/JGD2000/東京測地系を自動判別）
            pass
        else:  # 宣言が無い場合は JGD2011 系を仮定
            cmd += ["-s_srs", "EPSG:4612"]
        if layer is not None:
            cmd.append(layer)
        cmd += [str(out), str(gml)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"ogr2ogr 失敗: {gml.name}\n{r.stderr.strip()[:2000]}")
        outs.append(out)
    return outs


def _convert_with_osgeo(gml: Path, out_base: Path) -> list[Path]:
    """ogr2ogr が無い場合のフォールバック（osgeo.ogr で GeoJSON 化）。"""
    try:
        from osgeo import ogr, osr  # type: ignore
    except ImportError:
        print("osgeo (python gdal) が無いため pip install gdal を試みます…")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "gdal"], capture_output=True, text=True
        )
        if r.returncode != 0:
            print(r.stderr.strip()[-1500:], file=sys.stderr)
            _ensure_gdal_hint()
            raise SystemExit(2)
        try:
            from osgeo import ogr, osr  # type: ignore
        except ImportError:
            _ensure_gdal_hint()
            raise SystemExit(2)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ds = ogr.Open(str(gml))
    if ds is None:
        raise SystemExit(f"GML を開けませんでした: {gml}")
    _, legacy = _srs_of(gml)
    if legacy:
        print(f"  注意: {gml.name} は旧日本測地系の可能性があります（宣言に従い WGS84 へ変換）。")
    outs = []
    n_layers = ds.GetLayerCount()
    for i in range(n_layers):
        layer = ds.GetLayer(i)
        out = out_base if n_layers == 1 else out_base.with_name(f"{out_base.stem}__{layer.GetName()}.geojson")
        if out.exists():
            outs.append(out)
            continue
        src = layer.GetSpatialRef()
        if src is not None:
            src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        else:  # 宣言が無い場合は JGD2011 系を仮定
            src = osr.SpatialReference()
            src.ImportFromEPSG(4612)
            src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(src, dst)
        features = []
        for feat in layer:
            geom = feat.GetGeometryRef()
            if geom is not None:
                geom.Transform(ct)
            features.append(json.loads(feat.ExportToJson()))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
            encoding="utf-8",
        )
        outs.append(out)
    return outs


def _geometry_kind(geojsons: list[Path]) -> str:
    """GeoJSON 群のジオメトリ種から tippecanoe の --layer 名 (point/line/polygon) を決める.

    大きなファイルを避けるため各ファイル先頭 512KB をサンプリングする。
    """
    counts = {"point": 0, "line": 0, "polygon": 0}
    kinds = {
        "Point": "point", "MultiPoint": "point",
        "LineString": "line", "MultiLineString": "line",
        "Polygon": "polygon", "MultiPolygon": "polygon",
    }
    for gj in geojsons:
        with gj.open("rb") as f:
            head = f.read(512 * 1024).decode("utf-8", errors="replace")
        for gtype, k in kinds.items():
            counts[k] += len(re.findall(rf'"type":\s*"{gtype}"', head)) * head.count('"geometry"')
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        raise SystemExit("ジオメトリ種を判定できませんでした（GeoJSONが空の可能性）")
    return best


def _run_tippecanoe(tip: str, geojsons: list[Path], out: Path, layer: str) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [tip, "-zg", f"--layer={layer}", "--force", f"--output={out}"] + [str(g) for g in geojsons]
    print("  " + " ".join(cmd[:6]) + (" …" if len(cmd) > 7 else ""))
    # stdout は進捗スパムなので捨て、進捗・エラー（stderr）は表示する
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL)
    if r.returncode != 0:
        raise SystemExit(f"tippecanoe 失敗 (exit {r.returncode})")
    return out


def cmd_convert(args: argparse.Namespace) -> None:
    code = args.code
    out_pmtiles = PMTILES_DIR / f"{code}.pmtiles"
    if out_pmtiles.exists() and not args.force:
        print(f"スキップ（既存）: {out_pmtiles}")
        return
    data_files = _extract_zips(code)
    if not data_files:
        raise SystemExit("変換対象のデータファイルがありません")
    gj_dir = GEOJSON_DIR / code
    geojsons: list[Path] = []

    # 1) 同梱 GeoJSON があればそのまま使う（KSJ の 2024年度版 zip 等は
    #    WGS84 の GeoJSON を同梱しており、GDAL 無しで変換できる）
    bundled = [p for p in data_files if p.suffix.lower() == ".geojson"]
    for gj in bundled:
        dest = gj_dir / gj.name
        if dest.exists() and not args.force:
            print(f"スキップ（既存）: {dest.name}")
        else:
            print(f"同梱 GeoJSON を採用: {gj.name}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(gj, dest)
        geojsons.append(dest)

    # 2) 残り（GML / Shape）は ogr2ogr または osgeo で GeoJSON 化
    #    同梱 GeoJSON と同じファイル名基数（stem）のものは内容が重複するため常にスキップ
    to_convert = [p for p in data_files if p.suffix.lower() != ".geojson"]
    if to_convert:
        ogr = _find_ogr2ogr()
        for gml in to_convert:
            out_base = gj_dir / (gml.stem + ".geojson")
            existing = sorted(gj_dir.glob(f"{gml.stem}*.geojson")) if gj_dir.exists() else []
            if existing:
                names = ", ".join(p.name for p in existing[:3])
                print(f"スキップ（既存）: {names}" + (" ほか" if len(existing) > 3 else ""))
                geojsons.extend(existing)
                continue
            print(f"GML -> GeoJSON: {gml.name}")
            if ogr:
                geojsons.extend(_convert_with_ogr2ogr(ogr, gml, out_base))
            else:
                geojsons.extend(_convert_with_osgeo(gml, out_base))

    geojsons = sorted(set(geojsons))
    if not geojsons:
        raise SystemExit("GeoJSON が生成されませんでした")
    tip = _find_tippecanoe()
    if tip is None:
        print(
            "tippecanoe が見つかりません。先にビルドしてください:\n"
            "  scripts/ksj/build_tippecanoe.sh\n"
            "（または pacman: sudo pacman -S tippecanoe）\n"
            f"GeoJSON は生成済み: {gj_dir}",
            file=sys.stderr,
        )
        raise SystemExit(3)
    kind = _geometry_kind(geojsons)
    print(f"GeoJSON -> PMTiles (layer={kind}): {len(geojsons)} ファイル")
    result = _run_tippecanoe(tip, geojsons, out_pmtiles, kind)
    print(f"完了: {result} ({_human_size(result.stat().st_size)})")


# --------------------------------------------------------------------------
# catalog / files
# --------------------------------------------------------------------------
def cmd_catalog(args: argparse.Namespace) -> None:
    entries = load_catalog(refresh=args.refresh)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(entries)} 件 -> {out}")
    else:
        print(json.dumps(entries, ensure_ascii=False, indent=1))


def cmd_files(args: argparse.Namespace) -> None:
    files, visited = resolve_files(args.code, args.pref, args.year, refresh=args.refresh)
    if args.json:
        print(json.dumps(files, ensure_ascii=False, indent=1))
        return
    if not files:
        raise SystemExit(f"該当ファイルがありません: code={args.code} pref={args.pref} year={args.year}")
    if visited != [args.code]:
        print(f"# {args.code} はコンテナページのため下位データセットを辿りました: {', '.join(visited)}")
    for f in files:
        print(
            f"{f['pref_name'] or '全国':<6} {f['year']:<16} {f['size']:>10}  "
            f"{f['filename']}  [{f['code']}]"
        )
        print(f"    {f['url']}")
    print(f"\n{len(files)} 件")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    try:  # stdout/stderr の行バッファリング（進捗表示の順序を守る）
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--refresh", action="store_true", help="HTML キャッシュを無視して再取得")
    ap = argparse.ArgumentParser(
        description="国土数値情報(KSJ) GML -> PMTiles 変換パイプライン", parents=[common]
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("catalog", parents=[common], help="データセット一覧を JSON 出力")
    p.add_argument("--out", help="ファイルへ保存（無指定は stdout）")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("files", parents=[common], help="ダウンロード可能ファイル一覧（URL解決）")
    p.add_argument("code", help="データセットコード（例 N03, A29, A55）")
    p.add_argument("--pref", help="都道府県コード 2桁（例 47=沖縄）")
    p.add_argument("--year", type=int, help="西暦年で絞り込み（和暦も解釈）")
    p.add_argument("--json", action="store_true", help="JSON で出力")
    p.set_defaults(func=cmd_files)

    p = sub.add_parser("download", parents=[common], help="zip を data/raw/CODE/ へダウンロード（レジューム対応）")
    p.add_argument("code", help="データセットコード")
    p.add_argument("--pref", help="都道府県コード 2桁")
    p.add_argument("--year", type=int, help="西暦年で絞り込み")
    p.add_argument("--dry-run", action="store_true", help="URL 一覧のみ表示（DLしない）")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("convert", parents=[common], help="zip 解凍 -> GeoJSON -> PMTiles（冪等）")
    p.add_argument("code", help="データセットコード")
    p.add_argument("--force", action="store_true", help="既存成果物を再生成")
    p.set_defaults(func=cmd_convert)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
