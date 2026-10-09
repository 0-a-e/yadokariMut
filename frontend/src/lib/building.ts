/**
 * 建物単位集約の正規化層(Phase B2-α / docs/building-aggregation-b2-fe-plan.md §6.1)。
 *
 * BE /api/buildings/geojson の units 要素は search 結果 dict を原生で搭載するため、
 * types.ts の PropertyProperties(表示用に文字列化・整形済み)とはキー構成が非対称
 * (images は {image_url,...} 行配列 / access_summary は行リスト / station_summary 無し)。
 * ここで既存コンポーネント(PropertyCard / DetailPanel / AnalysisModal 等)が扱う
 * PropertyProperties 形状へ正規化し、建物データの正本(BuildingFeature[])から
 * 部屋平面リスト(PropertyFeature[])を派生する。B2-β 以降は各 UI が建物 Feature
 * を直接消費するが、部屋パネル・分析等の部屋オブジェクト需要は本層で供給する。
 */
import type {
  BuildingFeature,
  BuildingProperties,
  BuildingUnit,
  PropertyFeature,
  PropertyImageInfoLike,
  RoomView,
  ShortlistStatus,
} from '../types.ts';
import { isNearDuplicate, mediaImageUrl, type MediaImageLike } from './media.ts';
import { unitFloorOf } from './room.ts';

/** 部屋 id → 建物内位置の索引エントリ(buildRoomIndex の値) */
export interface RoomIndexEntry {
  buildingId: number;
  unitIndex: number;
}

/**
 * BuildingUnit(生の units 要素)→ RoomView(表示用ビュー)へ正規化。
 *
 * 上位集合型(D8)のため写像は「表示に最適化する 3 フィールド + 必須性の保証」だけ:
 * - images: sort_order 昇順の URL 文字列配列(行 dict → 文字列)
 * - access_summary: 行リスト → カンマ区切り文字列(部屋自身のアクセス行)
 * - station_summary: units は持たないため建物側の値を継承(検索・表示用)
 *
 * それ以外(所在階 floor_number / 向き orientation_deg / BE の生列)はスプレッドで
 * 素通しするため、BE が列を追加しても FE 側の対応漏れが構造的に起きない。
 */
export function normalizeUnit(
  unit: BuildingUnit,
  building: BuildingFeature['properties'],
): RoomView {
  return {
    ...unit,
    images: unitImagesToUrls(unit.images ?? []),
    access_summary: (unit.access_summary ?? []).join(', '),
    station_summary: building.station_summary ?? '',
    shortlist_status: unit.shortlist_status ?? 'none',
    stay_estimate: unit.stay_estimate ?? null,
    // BE 契約上は必須だが、応答欠落時にも消費側(配列走査・カンマ分割)が
    // 壊れないよう既定値を保証する(旧 normalizeUnit と同じ防御)
    feature_summary: unit.feature_summary ?? '',
    feature_categories: unit.feature_categories ?? [],
    rent_plans: unit.rent_plans ?? [],
    campaigns: unit.campaigns ?? [],
  };
}

/** images 行配列を sort_order 昇順の URL 文字列配列へ(gallery 共用) */
export function unitImagesToUrls(images: PropertyImageInfoLike[]): string[] {
  return [...images]
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
    .map((img) => img.image_url)
    .filter((u): u is string => Boolean(u));
}

/**
 * 建物配列 → 部屋平面リスト(PropertyFeature[])。
 * geometry は建物代表座標を全 units で共有(同一建物の部屋は同座標のため
 * 現行の部屋単位フィルタ(viewport/drawn)と実質同等)。
 */
export function flattenBuildingFeatures(buildings: BuildingFeature[]): PropertyFeature[] {
  const out: PropertyFeature[] = [];
  for (const b of buildings) {
    for (const unit of b.properties.units) {
      out.push({
        type: 'Feature',
        geometry: b.geometry,
        properties: normalizeUnit(unit, b.properties),
      });
    }
  }
  return out;
}

/** roomId → {buildingId, unitIndex} の索引(raw パッチ・選択解決用) */
export function buildRoomIndex(buildings: BuildingFeature[]): Map<number, RoomIndexEntry> {
  const index = new Map<number, RoomIndexEntry>();
  for (const b of buildings) {
    b.properties.units.forEach((u, i) => {
      index.set(u.id, { buildingId: b.properties.id, unitIndex: i });
    });
  }
  return index;
}

/** マーカー再構築 signature 用のショートリスト導出(設計 §4.1) */
export function countUnitsByStatus(
  units: BuildingUnit[],
  status: ShortlistStatus,
): number {
  let n = 0;
  for (const u of units) {
    if ((u.shortlist_status ?? 'none') === status) n += 1;
  }
  return n;
}

export function savedCountOf(building: BuildingFeature['properties']): number {
  return countUnitsByStatus(building.units, 'saved');
}

export function hiddenCountOf(building: BuildingFeature['properties']): number {
  return countUnitsByStatus(building.units, 'hide');
}

// ── B2-β: 地図 tooltip・建物カード用の表示導出 ──

/** 最安〜最高の帯(min==max または欠損は呼び出し側で単値/フォールバック扱い) */
export interface RentBand {
  min: number | null;
  max: number | null;
}

/**
 * units の stay_estimate.stayTotalYen の最安〜最高(設計 §4.1 の stay 帯)。
 * ok かつ stayTotalYen を保持する unit のみ対象。該当なしは両方 null。
 */
export function stayBandOfUnits(units: BuildingUnit[]): RentBand {
  let min: number | null = null;
  let max: number | null = null;
  for (const u of units) {
    const est = u.stay_estimate;
    if (!est?.ok || est.stayTotalYen == null) continue;
    if (min == null || est.stayTotalYen < min) min = est.stayTotalYen;
    if (max == null || est.stayTotalYen > max) max = est.stayTotalYen;
  }
  return { min, max };
}

/** 建物表示名のフォールバック上限(canonical 名欠損時の municipality+address 短縮長) */
export const BUILDING_NAME_FALLBACK_MAX = 24;

/**
 * 建物の表示名(canonical 名)。無名は municipality+address の短縮(設計 §4.1)。
 * どちらも無い場合は固定ラベル。
 */
export function buildingDisplayName(p: BuildingFeature['properties']): string {
  if (p.name) return p.name;
  const fallback = [p.municipality, p.address].filter(Boolean).join(' ').trim();
  if (!fallback) return '名称未設定の建物';
  return fallback.length > BUILDING_NAME_FALLBACK_MAX
    ? `${fallback.slice(0, BUILDING_NAME_FALLBACK_MAX)}…`
    : fallback;
}

/**
 * 築年・構造のスペック(「2015年築」「RC」)。階数を伴わない単独表示
 * (建物パネルの「築年 / 構造」行など)が使う下位の正本。
 */
export function buildingAgeStructureParts(p: BuildingProperties): string[] {
  return [
    p.built_year != null ? `${p.built_year}年築` : null,
    p.structure ?? null,
  ].filter((v): v is string => Boolean(v));
}

/**
 * 建物スペック行の正本(「2015年築 · RC · 8階建」)。
 * カード / 建物パネル / 地図 tooltip / AI カードの 4 箇所が共有する
 * (docs/fe-floor-orientation-redesign-plan.md §7.2・ラベル規約の統一)。
 * 階数は buildingFloorsLabel(確定値と下限で表記が変わる)を正本とする。
 */
export function buildingSpecParts(p: BuildingProperties): string[] {
  return [
    ...buildingAgeStructureParts(p),
    buildingFloorsLabel(buildingFloorInfo(p)),
  ].filter((v): v is string => Boolean(v));
}

/**
 * 建物階数の導出(要件2 / docs/fe-floor-orientation-redesign-plan.md §5)。
 *
 * - `known`: buildings.building_floors(bratto 由来の確定値・多数決代表値)
 * - `lowerBound`: 掲載部屋の最高所在階(確定値が無いソース=unionmonthly の代替)。
 *   部屋が 6 階にあれば建物は 6 階以上——**下限であって階数そのものではない**
 * - `unitFloorRange`: 掲載部屋の階数レンジ(地下・不明は除外)
 */
export interface BuildingFloorInfo {
  known: number | null;
  lowerBound: number | null;
  unitFloorRange: { min: number; max: number } | null;
}

export function buildingFloorInfo(p: BuildingProperties): BuildingFloorInfo {
  const known = p.building_floors ?? null;
  const floors: number[] = [];
  for (const u of p.units) {
    const f = unitFloorOf(u);
    if (f != null) floors.push(f);
  }
  const lowerBound = floors.length > 0 ? Math.max(...floors) : null;
  const unitFloorRange =
    floors.length > 0 ? { min: Math.min(...floors), max: lowerBound! } : null;
  return { known, lowerBound, unitFloorRange };
}

/**
 * 建物階数の表示値。確定値は「8階建」、確定値が無く掲載部屋がある場合は
 * 下限を「6階以上」と表記する(N階建 と断定しない。§5.1 決定 D5)。
 */
export function buildingFloorsLabel(info: BuildingFloorInfo): string | null {
  if (info.known != null) return `${info.known}階建`;
  if (info.lowerBound != null) return `${info.lowerBound}階以上`;
  return null;
}

/** 建物の部屋数(意味論の正本・A4 解消)。BE キャッシュ列を優先する */
export interface RoomCounts {
  total: number;
  active: number;
  saved: number;
  hidden: number;
}

/**
 * 部屋数の正本。total / active は BE キャッシュ列(units_count /
 * active_units_count)を優先する: stay モードでは Worker が est 不能 unit を
 * units から除去するため(§7 A4)、units.length を件数表示に使うと
 * 「掲載中 N 部屋」がフィルタ操作で揺れる。saved / hidden は units 走査。
 */
export function roomCounts(p: BuildingProperties): RoomCounts {
  const total = p.units_count ?? p.units.length;
  const active =
    p.active_units_count ?? p.units.filter((u) => u.is_active !== false).length;
  return { total, active, saved: savedCountOf(p), hidden: hiddenCountOf(p) };
}

/** 部屋一覧の並び順キー(§6.3) */
export type RoomSortKey = 'price' | 'floor';

/** 並び順の方向(asc=低い順 / desc=高い順) */
export type RoomSortDir = 'asc' | 'desc';

/** 部屋一覧の並び順モード(セレクトの値と 1:1 に対応する) */
export type RoomSortMode = `${RoomSortKey}_${RoomSortDir}`;

/**
 * 並び順セレクトの選択肢の正本(§6.3)。
 * `direction` は表示アロー(asc=上向き / desc=下向き)の指示で、
 * ラベル文言は「低い順 / 高い順」を明示する(アローだけでは誤読し得るため)。
 */
export const ROOM_SORT_OPTIONS: readonly {
  value: RoomSortMode;
  label: string;
  direction: RoomSortDir;
}[] = [
  { value: 'price_asc', label: '価格 低い順', direction: 'asc' },
  { value: 'price_desc', label: '価格 高い順', direction: 'desc' },
  { value: 'floor_asc', label: '階 低い順', direction: 'asc' },
  { value: 'floor_desc', label: '階 高い順', direction: 'desc' },
];

/** 部屋一覧の既定の並び順(最安順。現行挙動を維持する) */
export const ROOM_SORT_DEFAULT: RoomSortMode = 'price_asc';

/**
 * 部屋行ソートの正本(設計 §4.2 + §6.3)。
 * matched 部屋を常に上位へ。各グループ内は active 優先 → モード別キー → id 順:
 * - 'price_asc' / 'price_desc': 最安日額の昇順・降順(既定は昇順=現行挙動)
 * - 'floor_asc' / 'floor_desc': 所在階の昇順・降順
 * 値が不明な部屋(日額なし・階数なし・地下のみ)は**方向に関わらず末尾**に置く
 * (「高層から見たい」ときに不明が先頭へ来ると読めないため)。
 */
export function sortRooms(
  units: BuildingUnit[],
  matchedRoomIds: ReadonlySet<number>,
  mode: RoomSortMode = ROOM_SORT_DEFAULT,
): BuildingUnit[] {
  const floorKey = mode.startsWith('floor');
  const dir = mode.endsWith('desc') ? -1 : 1;
  const valueOf = (u: BuildingUnit): number | null =>
    floorKey ? unitFloorOf(u) : (u.min_daily_rent ?? null);
  return [...units].sort((a, b) => {
    const ma = matchedRoomIds.has(a.id) ? 0 : 1;
    const mb = matchedRoomIds.has(b.id) ? 0 : 1;
    if (ma !== mb) return ma - mb;
    const ia = a.is_active === false ? 1 : 0;
    const ib = b.is_active === false ? 1 : 0;
    if (ia !== ib) return ia - ib;
    // モード別キー(不明は方向に関わらず末尾へ)
    const va = valueOf(a);
    const vb = valueOf(b);
    if (va == null && vb != null) return 1;
    if (va != null && vb == null) return -1;
    if (va != null && vb != null && va !== vb) return (va - vb) * dir;
    // 同値(または両方不明)のタイブレーク: 日額昇順 → id 順
    // (階順の同階では最安の部屋を先に出す。価格順では日額が一致するため no-op)
    const ra = a.min_daily_rent ?? Number.POSITIVE_INFINITY;
    const rb = b.min_daily_rent ?? Number.POSITIVE_INFINITY;
    if (ra !== rb) return ra - rb;
    return a.id - b.id;
  });
}

// ── 建物ギャラリー合成(2026-10-09 承認仕様・設計 §4.3) ──

/**
 * units images 行。BE のメディア拡張(media_id / dhash / has_thumb)を構造型で受ける
 * (schema.d.ts 再生成の前後どちらでもコンパイル可能・docs/media-storage-rustfs-plan.md §2.7)。
 */
export type GalleryImageRow = PropertyImageInfoLike & MediaImageLike;

/**
 * ギャラリーのスライド 1 枚。type は image_type(gallery/thumbnail/floorplan)の受け皿。
 * url はカルーセル用(thumb variant 優先)、fullUrl はライトボックス用オリジナル。
 */
export interface BuildingGallerySlide {
  url: string;
  /** ライトボックス用オリジナル URL(media_id が無ければ url と同じ外部 URL) */
  fullUrl?: string;
  /** 近重複畳み込みの判定元 dHash(代表写真は不明で null) */
  dhash?: string | null;
  type?: string | null;
  unitId?: number;
}

/** 代表写真 + 追加 49 枚(承認: 実測で dedup 後平均 65.1 枚・50 枚超 603 棟) */
export const GALLERY_MAX_SLIDES = 50;

/** 既定 dedup キー: media_id 優先・fallback = image_url(§2.7 の差し替え実装) */
function defaultGalleryDedupKey(img: GalleryImageRow): string {
  return img.media_id != null ? `m${img.media_id}` : (img.image_url ?? '');
}

export interface ComposeGalleryOptions {
  /**
   * 写真群内の dedup キー(既定 = media_id ?? image_url)。BE のクラスタ代表ストア導入済み
   * で同一クラスタは同じ media_id に集約されるため、既定キーは media_id 優先
   * (バックフィル未了行は URL へフォールバック)。代表写真は URL のみの情報のため
   * 常に URL 比較(採用済み URL との一致で除去)。
   */
  dedupKey?: (img: GalleryImageRow) => string;
  /** スライド上限(既定 50)。テスト用 */
  max?: number;
}

/**
 * 建物ギャラリーを合成する純関数。
 *
 * - 1 枚目 = 代表写真(building.thumbnail_url。null は代表なしで開始)
 * - 2 枚目以降 = 全 units の images から dedupKey(既定 media_id・fallback URL)一致
 *   + 採用済み URL 一致(代表との一致+群内一致)+ dHash 近重複(距離 <= 8)を除去
 * - 順序 = units 順(BE: active 優先→最安順)× 部屋内 sort_order
 * - ImageCarousel へは slide.url(thumb)を、ライトボックスへは slide.fullUrl を渡す
 */
export function composeBuildingGallery(
  building: BuildingFeature['properties'],
  options?: ComposeGalleryOptions,
): BuildingGallerySlide[] {
  const dedupKey = options?.dedupKey ?? defaultGalleryDedupKey;
  const max = options?.max ?? GALLERY_MAX_SLIDES;

  const slides: BuildingGallerySlide[] = [];
  /** dedupKey の既出集合(クラスタ media_id / URL フォールバック) */
  const seenKeys = new Set<string>();
  /** 既出 URL 集合(代表写真は URL のみの情報のため URL 比較・media_id 付き行とも照合) */
  const seenUrls = new Set<string>();
  /** 採用済みスライドの dHash(近重複畳み込み用。代表は不明のため不入) */
  const seenHashes: string[] = [];
  if (building.thumbnail_url) {
    slides.push({
      url: building.thumbnail_url,
      fullUrl: building.thumbnail_url,
      dhash: null,
      type: 'thumbnail',
    });
    seenKeys.add(building.thumbnail_url);
    seenUrls.add(building.thumbnail_url);
  }

  outer: for (const unit of building.units) {
    const imgs: GalleryImageRow[] = [...(unit.images ?? [])].sort(
      (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0),
    );
    for (const img of imgs) {
      const sourceUrl = img.image_url;
      if (!sourceUrl) continue;
      const key = dedupKey(img) || sourceUrl;
      if (seenKeys.has(key) || seenUrls.has(sourceUrl)) continue;
      // 近重複(同一写真の再エンコード/サイズ違いが別クラスタに跨ったケース)を畳む
      if (img.dhash && seenHashes.some((h) => isNearDuplicate(h, img.dhash))) continue;
      seenKeys.add(key);
      seenUrls.add(sourceUrl);
      if (img.dhash) seenHashes.push(img.dhash);
      slides.push({
        url: mediaImageUrl(img, 'thumb') ?? sourceUrl,
        fullUrl: mediaImageUrl(img) ?? sourceUrl,
        dhash: img.dhash ?? null,
        type: img.image_type,
        unitId: unit.id,
      });
      if (slides.length >= max) break outer;
    }
  }
  return slides;
}

/**
 * 「この建物をまとめて非表示」の対象部屋(計画 §4.3 承認: saved 以外の active
 * 可視部屋へ hide。saved は保護・reject/hide 済みはスキップ)。
 * 対象 0 件(全部屋 saved 済み等)は null を返し呼び出し側でボタンを無効化する。
 */
export function bulkHideTargetUnits(
  building: BuildingFeature['properties'],
): BuildingUnit[] | null {
  const targets = building.units.filter((u) => {
    if (u.is_active === false) return false;
    const status = u.shortlist_status ?? 'none';
    return status === 'none';
  });
  return targets.length > 0 ? targets : null;
}
