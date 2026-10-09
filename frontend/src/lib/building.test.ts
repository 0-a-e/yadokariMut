import { describe, expect, it } from 'vitest';
import {
  buildRoomIndex,
  buildingDisplayName,
  buildingFloorInfo,
  buildingFloorsLabel,
  buildingSpecParts,
  bulkHideTargetUnits,
  composeBuildingGallery,
  countUnitsByStatus,
  flattenBuildingFeatures,
  hiddenCountOf,
  normalizeUnit,
  roomCounts,
  savedCountOf,
  sortRooms,
  stayBandOfUnits,
  BUILDING_NAME_FALLBACK_MAX,
  GALLERY_MAX_SLIDES,
} from './building.ts';
import type {
  BuildingFeature,
  BuildingUnit,
  PropertyImageInfoLike,
} from '../types.ts';

function img(
  url: string,
  opts?: {
    type?: string | null;
    order?: number;
    /** メディア拡張(BE 契約・schema.d.ts 再生成前でも組めるようキャストで搭載) */
    mediaId?: number | null;
    dhash?: string | null;
    hasThumb?: boolean | null;
  },
): PropertyImageInfoLike {
  return {
    image_url: url,
    image_type: opts?.type ?? 'gallery',
    sort_order: opts?.order ?? 0,
    ...(opts?.mediaId !== undefined ? { media_id: opts.mediaId } : {}),
    ...(opts?.dhash !== undefined ? { dhash: opts.dhash } : {}),
    ...(opts?.hasThumb !== undefined ? { has_thumb: opts.hasThumb } : {}),
  } as PropertyImageInfoLike;
}

function unit(id: number, partial: Partial<BuildingUnit> = {}): BuildingUnit {
  return {
    id,
    source_site: 'unionmonthly',
    title: `Room${id}`,
    layout: '1K',
    area_m2: 25,
    min_daily_rent: 4800,
    min_plan_total: 144000,
    total_score: 0,
    shortlist_status: 'none',
    is_active: true,
    access_summary: ['JR 渋谷駅 徒歩5分'],
    images: [],
    feature_summary: '',
    feature_categories: ['elevator'],
    rent_plans: [],
    campaigns: [],
    ...partial,
  };
}

function bldg(
  id: number,
  units: BuildingUnit[],
  partial: Partial<BuildingFeature['properties']> = {},
  coords: [number, number] = [139.7, 35.6],
): BuildingFeature {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: coords },
    properties: {
      id,
      kind: 'building',
      name: `Building${id}`,
      address: '東京都多摩市永山1-1',
      prefecture_name: '東京都',
      municipality: '多摩市',
      is_active: units.some((u) => u.is_active),
      units_count: units.length,
      active_units_count: units.filter((u) => u.is_active).length,
      source_sites: [...new Set(units.map((u) => u.source_site ?? ''))].filter(Boolean),
      building_names: [],
      feature_categories: [],
      min_daily_rent: units.reduce<number | null>(
        (m, u) => (u.min_daily_rent == null ? m : m == null ? u.min_daily_rent : Math.min(m, u.min_daily_rent)),
        null,
      ),
      max_daily_rent: units.reduce<number | null>(
        (m, u) => (u.min_daily_rent == null ? m : m == null ? u.min_daily_rent : Math.max(m, u.min_daily_rent)),
        null,
      ),
      min_plan_total: 144000,
      has_campaign: false,
      access_summary: ['JR 渋谷駅 徒歩5分'],
      station_summary: '渋谷',
      thumbnail_url: null,
      ...partial,
      units,
    },
  };
}

describe('normalizeUnit', () => {
  const b = bldg(1, [unit(10)]);

  it('images 行配列を sort_order 昇順の URL 配列へ変換する', () => {
    const u = unit(10, {
      images: [img('b.jpg', { order: 2 }), img('a.jpg', { order: 1 }), img('c.jpg', { order: 0 })],
    });
    expect(normalizeUnit(u, b.properties).images).toEqual(['c.jpg', 'a.jpg', 'b.jpg']);
  });

  it('access_summary 行リストをカンマ区切りへ結合し、station_summary は建物側を継承する', () => {
    const u = unit(10, { access_summary: ['JR 渋谷駅 徒歩5分', '京王 聖蹟桜ヶ丘駅 徒歩12分'] });
    const props = normalizeUnit(u, b.properties);
    expect(props.access_summary).toBe('JR 渋谷駅 徒歩5分, 京王 聖蹟桜ヶ丘駅 徒歩12分');
    expect(props.station_summary).toBe('渋谷');
  });

  it('feature_summary は unit の値を引き継ぐ(B2-ε で BE 供給・欠落は空文字)', () => {
    const u = unit(10, { feature_summary: 'オートロック, 浴室乾燥機' });
    expect(normalizeUnit(u, b.properties).feature_summary).toBe('オートロック, 浴室乾燥機');
    expect(normalizeUnit(unit(11, { feature_summary: undefined }), b.properties).feature_summary).toBe('');
  });

  it('shortlist_status の null は none 扱い', () => {
    const props = normalizeUnit(unit(10, { shortlist_status: null }), b.properties);
    expect(props.shortlist_status).toBe('none');
  });

  it('FE 派生フィールド(stay_estimate / shortlist_comment / price_history)を引き継ぐ', () => {
    const u = unit(10, {
      stay_estimate: { ok: false, stayDays: 0, stayTotalYen: null, rentDailyYen: null, selectedPlanCode: null, usedFallback: false, planLabel: null },
      shortlist_comment: 'memo',
    });
    const props = normalizeUnit(u, b.properties);
    expect(props.stay_estimate?.ok).toBe(false);
    expect(props.shortlist_comment).toBe('memo');
  });
});

describe('flattenBuildingFeatures / buildRoomIndex', () => {
  const b1 = bldg(1, [unit(10), unit(11)]);
  const b2 = bldg(2, [unit(20)], {}, [140.1, 36.2]);

  it('全 units を平面化し geometry は建物代表座標を共有する', () => {
    const flat = flattenBuildingFeatures([b1, b2]);
    expect(flat.map((f) => f.properties.id)).toEqual([10, 11, 20]);
    expect(flat[0].geometry).toBe(b1.geometry);
    expect(flat[2].geometry.coordinates).toEqual([140.1, 36.2]);
  });

  it('roomId → {buildingId, unitIndex} の索引を構築する', () => {
    const index = buildRoomIndex([b1, b2]);
    expect(index.get(11)).toEqual({ buildingId: 1, unitIndex: 1 });
    expect(index.get(20)).toEqual({ buildingId: 2, unitIndex: 0 });
    expect(index.size).toBe(3);
  });
});

describe('countUnitsByStatus', () => {
  it('saved / hide を建物 units から数える(sig 導出・設計 §4.1)', () => {
    const b = bldg(1, [
      unit(10, { shortlist_status: 'saved' }),
      unit(11, { shortlist_status: 'hide' }),
      unit(12, { shortlist_status: 'saved' }),
      unit(13, { shortlist_status: null }),
    ]);
    expect(savedCountOf(b.properties)).toBe(2);
    expect(hiddenCountOf(b.properties)).toBe(1);
    expect(countUnitsByStatus(b.properties.units, 'reject')).toBe(0);
  });
});

// ── B2-β: 地図 tooltip・建物カード用の表示導出 ──

function stayEst(total: number | null, ok = true) {
  return {
    ok,
    stayDays: 30,
    stayTotalYen: total,
    rentDailyYen: total != null ? total / 30 : null,
    selectedPlanCode: null,
    usedFallback: false,
    planLabel: null,
  };
}

describe('stayBandOfUnits(stay 帯・設計 §4.1)', () => {
  it('ok かつ stayTotalYen 保持の unit の最安〜最高を返す', () => {
    const band = stayBandOfUnits([
      unit(10, { stay_estimate: stayEst(200000) }),
      unit(11, { stay_estimate: stayEst(100000) }),
      unit(12, { stay_estimate: stayEst(150000) }),
    ]);
    expect(band).toEqual({ min: 100000, max: 200000 });
  });

  it('ok=false / stayTotalYen null の unit は除外する', () => {
    const band = stayBandOfUnits([
      unit(10, { stay_estimate: stayEst(null) }),
      unit(11, { stay_estimate: stayEst(120000, false) }),
      unit(12, { stay_estimate: stayEst(180000) }),
    ]);
    expect(band).toEqual({ min: 180000, max: 180000 });
  });

  it('該当 unit 無しは両方 null(呼び出し側でカタログ帯へフォールバック)', () => {
    expect(stayBandOfUnits([])).toEqual({ min: null, max: null });
    expect(stayBandOfUnits([unit(10, { stay_estimate: null })])).toEqual({
      min: null,
      max: null,
    });
  });
});

describe('buildingDisplayName(無名フォールバック)', () => {
  it('canonical 名があればそのまま返す', () => {
    expect(buildingDisplayName(bldg(1, [unit(10)]).properties)).toBe('Building1');
  });

  it('無名は municipality+address を結合し、長い場合は短縮する', () => {
    const p = bldg(1, [unit(10)], { name: null, municipality: '多摩市', address: 'あ'.repeat(30) }).properties;
    const combined = '多摩市 ' + 'あ'.repeat(30);
    expect(buildingDisplayName(p)).toBe(`${combined.slice(0, BUILDING_NAME_FALLBACK_MAX)}…`);

    const short = bldg(2, [unit(20)], { name: null, municipality: '多摩市', address: '永山1-1' }).properties;
    expect(buildingDisplayName(short)).toBe('多摩市 永山1-1');
  });

  it('municipality / address も無い場合は固定ラベル', () => {
    const p = bldg(1, [unit(10)], { name: null, municipality: null, address: null }).properties;
    expect(buildingDisplayName(p)).toBe('名称未設定の建物');
  });
});

describe('sortRooms(部屋行ソートの正本・§4.2/§6.3)', () => {
  const units = [
    unit(10, { min_daily_rent: 5000 }),
    unit(11, { min_daily_rent: 4800, is_active: false }),
    unit(12, { min_daily_rent: 6000 }),
    unit(13, { min_daily_rent: 4500, is_active: false }),
    unit(14, { min_daily_rent: 7000 }),
  ];

  it('matched 部屋を上位へ出し、各グループ内は active 優先→最安日額→id 順', () => {
    const sorted = sortRooms(units, new Set([14, 11]));
    // matched グループ: 14(active) → 11(inactive)。unmatched グループ:
    // active の 10→12(最安順) → inactive の 13
    expect(sorted.map((u) => u.id)).toEqual([14, 11, 10, 12, 13]);
  });

  it('matched 無しは元の群全体が active 優先→最安順に並ぶ', () => {
    const sorted = sortRooms(units, new Set());
    expect(sorted.map((u) => u.id)).toEqual([10, 12, 14, 13, 11]);
  });

  it('元配列を破壊しない', () => {
    sortRooms(units, new Set([10]));
    expect(units.map((u) => u.id)).toEqual([10, 11, 12, 13, 14]);
  });

  it('floor_asc は所在階昇順(不明は末尾)・同階は最安順', () => {
    const withFloors = [
      unit(10, { floor_number: 5, min_daily_rent: 5000 }),
      unit(11, { floor_number: null }),
      unit(12, { floor_number: 2, min_daily_rent: 6000 }),
      unit(13, { floor_number: 2, min_daily_rent: 4500 }),
    ];
    expect(sortRooms(withFloors, new Set(), 'floor_asc').map((u) => u.id)).toEqual([
      13, 12, 10, 11,
    ]);
    // matched 優先はモード共通
    expect(sortRooms(withFloors, new Set([11]), 'floor_asc').map((u) => u.id)).toEqual([
      11, 13, 12, 10,
    ]);
  });

  it('floor_desc は所在階降順(不明はやはり末尾)', () => {
    const withFloors = [
      unit(10, { floor_number: 5, min_daily_rent: 5000 }),
      unit(11, { floor_number: null }),
      unit(12, { floor_number: 2, min_daily_rent: 6000 }),
      unit(13, { floor_number: 8, min_daily_rent: 4500 }),
    ];
    // 高層 → 低層。階数不明は方向に関わらず末尾(読めない行を先頭に出さない)
    expect(sortRooms(withFloors, new Set(), 'floor_desc').map((u) => u.id)).toEqual([
      13, 10, 12, 11,
    ]);
  });

  it('price_desc は日額降順(日額なしは末尾)・price_asc は現行既定', () => {
    const withRents = [
      unit(10, { min_daily_rent: 5000 }),
      unit(11, { min_daily_rent: null }),
      unit(12, { min_daily_rent: 8000 }),
      unit(13, { min_daily_rent: 3000 }),
    ];
    expect(sortRooms(withRents, new Set(), 'price_desc').map((u) => u.id)).toEqual([
      12, 10, 13, 11,
    ]);
    expect(sortRooms(withRents, new Set(), 'price_asc').map((u) => u.id)).toEqual([
      13, 10, 12, 11,
    ]);
    // 既定(引数省略)は price_asc = 最安順
    expect(sortRooms(withRents, new Set()).map((u) => u.id)).toEqual([13, 10, 12, 11]);
  });
});

describe('buildingSpecParts(建物スペック行の正本・§7.2)', () => {
  it('築年・構造・階数を「2015年築 / RC / 8階建」の順で返す', () => {
    const b = bldg(1, [unit(10)], { built_year: 2015, structure: 'RC', building_floors: 8 });
    expect(buildingSpecParts(b.properties)).toEqual(['2015年築', 'RC', '8階建']);
  });

  it('欠損は落とし、全て欠損なら空配列', () => {
    const b = bldg(1, [unit(10)], { built_year: null, structure: null, building_floors: null });
    expect(buildingSpecParts(b.properties)).toEqual([]);
  });
});

describe('buildingFloorInfo / buildingFloorsLabel(建物階数・§5)', () => {
  it('確定値(building_floors)を優先し「N階建」と表示する', () => {
    const b = bldg(
      1,
      [unit(10, { floor_number: 3 }), unit(11, { floor_number: 6 })],
      { building_floors: 10 },
    );
    const info = buildingFloorInfo(b.properties);
    expect(info.known).toBe(10);
    expect(info.lowerBound).toBe(6);
    expect(info.unitFloorRange).toEqual({ min: 3, max: 6 });
    expect(buildingFloorsLabel(info)).toBe('10階建');
  });

  it('確定値が無い場合は掲載部屋の最高階を「N階以上」と表示する(断定しない)', () => {
    const b = bldg(
      1,
      [unit(10, { floor_number: 1 }), unit(11, { floor_number_max: 6, floor_number: 5 })],
      { building_floors: null },
    );
    const info = buildingFloorInfo(b.properties);
    expect(info.known).toBeNull();
    expect(info.lowerBound).toBe(6);
    expect(buildingFloorsLabel(info)).toBe('6階以上');
  });

  it('地下・不明は階数の導出に使わない(どちらも無ければ null)', () => {
    const basement = bldg(1, [unit(10, { floor_number: -1 })], { building_floors: null });
    expect(buildingFloorInfo(basement.properties).lowerBound).toBeNull();
    expect(buildingFloorsLabel(buildingFloorInfo(basement.properties))).toBeNull();
  });
});

describe('roomCounts(部屋数の意味論の正本・A4)', () => {
  it('BE キャッシュ列を優先する(stay モードで units が間引かれても揺れない)', () => {
    const b = bldg(1, [unit(10, { shortlist_status: 'saved' }), unit(11, { shortlist_status: 'hide' })], {
      units_count: 5,
      active_units_count: 4,
    });
    expect(roomCounts(b.properties)).toEqual({ total: 5, active: 4, saved: 1, hidden: 1 });
  });

  it('キャッシュ列が無ければ units から導出する', () => {
    const b = bldg(1, [unit(10), unit(11, { is_active: false })], {
      units_count: undefined,
      active_units_count: undefined,
    });
    expect(roomCounts(b.properties)).toEqual({ total: 2, active: 1, saved: 0, hidden: 0 });
  });
});

describe('composeBuildingGallery(2026-10-09 承認仕様)', () => {
  it('代表写真が先頭。thumbnail_url が null なら代表なしで開始する', () => {
    const withRep = bldg(1, [unit(10, { images: [img('a.jpg')] })], { thumbnail_url: 'rep.jpg' });
    expect(composeBuildingGallery(withRep.properties).map((s) => s.url)).toEqual(['rep.jpg', 'a.jpg']);

    const noRep = bldg(2, [unit(10, { images: [img('a.jpg')] })], { thumbnail_url: null });
    expect(composeBuildingGallery(noRep.properties).map((s) => s.url)).toEqual(['a.jpg']);
  });

  it('URL 一致 dedup: 代表との一致と写真群内の一致を除去する', () => {
    const b = bldg(
      1,
      [
        unit(10, { images: [img('shared.jpg'), img('u10.jpg')] }),
        unit(11, { images: [img('shared.jpg'), img('u11.jpg')] }),
      ],
      { thumbnail_url: 'shared.jpg' },
    );
    expect(composeBuildingGallery(b.properties).map((s) => s.url)).toEqual([
      'shared.jpg',
      'u10.jpg',
      'u11.jpg',
    ]);
  });

  it('順序は units 順 × 部屋内 sort_order。スライドは type/unitId を保持する', () => {
    const b = bldg(1, [
      unit(10, { images: [img('a2.jpg', { order: 2 }), img('a1.jpg', { order: 1, type: 'floorplan' })] }),
      unit(11, { images: [img('b1.jpg')] }),
    ]);
    const slides = composeBuildingGallery(b.properties);
    expect(slides).toEqual([
      { url: 'a1.jpg', fullUrl: 'a1.jpg', dhash: null, type: 'floorplan', unitId: 10 },
      { url: 'a2.jpg', fullUrl: 'a2.jpg', dhash: null, type: 'gallery', unitId: 10 },
      { url: 'b1.jpg', fullUrl: 'b1.jpg', dhash: null, type: 'gallery', unitId: 11 },
    ]);
  });

  it(`ソフトキャップ = 代表+${GALLERY_MAX_SLIDES - 1} 枚で打ち切る`, () => {
    const many = Array.from({ length: 200 }, (_, i) => img(`p${i}.jpg`));
    const b = bldg(1, [unit(10, { images: many })], { thumbnail_url: 'rep.jpg' });
    const slides = composeBuildingGallery(b.properties);
    expect(slides).toHaveLength(GALLERY_MAX_SLIDES);
    expect(slides[0].url).toBe('rep.jpg');
    expect(slides[1].url).toBe('p0.jpg');
  });

  it('dedupKey は注入可能(BE pHash 列追加時の切替受け入れ)', () => {
    const b = bldg(1, [
      unit(10, { images: [img('url-a.jpg', { order: 1 })] }),
      unit(11, { images: [img('url-b.jpg', { order: 2 })] }),
    ]);
    // image_type を疑似 hash キーとして注入 → 群内で同一 type の画像は dedup される
    const slides = composeBuildingGallery(b.properties, {
      dedupKey: (i) => String(i.image_type ?? ''),
    });
    expect(slides.map((s) => s.url)).toEqual(['url-a.jpg']);
  });

  // ── media_id / dHash 導入後(計画 §2.7) ──

  it('media_id dedup: 同一クラスタは URL 違いでも media_id キーで 1 枚に畳む', () => {
    const b = bldg(1, [
      unit(10, { images: [img('https://a.example/x.jpg', { mediaId: 7, hasThumb: true })] }),
      unit(11, {
        images: [
          // 同一クラスタの再エンコード/サイズ違い(別 URL・同一 media_id)
          img('https://b.example/y-s.jpg', { mediaId: 7, hasThumb: true }),
          img('https://b.example/z.jpg', { mediaId: 8, hasThumb: true }),
        ],
      }),
    ]);
    const slides = composeBuildingGallery(b.properties);
    expect(slides.map((s) => s.url)).toEqual([
      '/api/media/7?variant=thumb',
      '/api/media/8?variant=thumb',
    ]);
    // ライトボックスはオリジナル(variant なし)
    expect(slides.map((s) => s.fullUrl)).toEqual(['/api/media/7', '/api/media/8']);
  });

  it('media_id 無し行(バックフィル未了)は従来どおり外部 URL=完全後方互換', () => {
    const b = bldg(1, [unit(10, { images: [img('https://ext.example/a.jpg')] })]);
    expect(composeBuildingGallery(b.properties)).toEqual([
      {
        url: 'https://ext.example/a.jpg',
        fullUrl: 'https://ext.example/a.jpg',
        dhash: null,
        type: 'gallery',
        unitId: 10,
      },
    ]);
  });

  it('has_thumb が無い media は variant を付けない(404 回避)', () => {
    const b = bldg(1, [unit(10, { images: [img('x.jpg', { mediaId: 9, hasThumb: false })] })]);
    expect(composeBuildingGallery(b.properties)[0]).toMatchObject({
      url: '/api/media/9',
      fullUrl: '/api/media/9',
    });
  });

  it('代表写真 URL と media_id 付き行の URL 一致も畳む(代表は dHash 不明で URL 比較のみ)', () => {
    const b = bldg(
      1,
      [unit(10, { images: [img('rep.jpg', { mediaId: 5, hasThumb: true })] })],
      { thumbnail_url: 'rep.jpg' },
    );
    expect(composeBuildingGallery(b.properties).map((s) => s.url)).toEqual(['rep.jpg']);
  });

  it('dHash 近重複: 距離 <= 8 は畳み込み、別写真(距離 28 相当)は別スライドとして残す', () => {
    const b = bldg(1, [
      unit(10, { images: [img('a.jpg', { dhash: '0000000000000000' })] }),
      unit(11, {
        images: [
          // 距離 2(同一写真の再エンコード)→ 畳む
          img('a-reencoded.jpg', { dhash: '0000000000000003' }),
          // 距離 28(別写真)→ 残す
          img('b.jpg', { dhash: '000000000fffffff' }),
        ],
      }),
    ]);
    const slides = composeBuildingGallery(b.properties);
    expect(slides.map((s) => s.url)).toEqual(['a.jpg', 'b.jpg']);
    expect(slides[0].dhash).toBe('0000000000000000');
  });

  it('dHash 未計算(null)は近重複畳み込みの対象にしない', () => {
    const b = bldg(1, [
      unit(10, { images: [img('a.jpg', { dhash: null }), img('b.jpg', { dhash: null })] }),
    ]);
    expect(composeBuildingGallery(b.properties).map((s) => s.url)).toEqual(['a.jpg', 'b.jpg']);
  });
});

describe('bulkHideTargetUnits(まとめて非表示・計画 §4.3 承認)', () => {
  it('saved 以外の active 部屋のみ対象。非 active・saved・hide/reject 済みは除外', () => {
    const b = bldg(1, [
      unit(10, { shortlist_status: 'none' }),
      unit(11, { shortlist_status: 'saved' }),
      unit(12, { shortlist_status: 'hide' }),
      unit(13, { shortlist_status: 'reject' }),
      unit(14, { is_active: false, shortlist_status: 'none' }),
      unit(15, { shortlist_status: null }),
    ]);
    expect(bulkHideTargetUnits(b.properties)?.map((u) => u.id)).toEqual([10, 15]);
  });

  it('対象 0 件(全部屋 saved/処理済み)は null(ボタン無効化)', () => {
    const b = bldg(1, [unit(10, { shortlist_status: 'saved' }), unit(11, { shortlist_status: 'hide' })]);
    expect(bulkHideTargetUnits(b.properties)).toBeNull();
  });
});
