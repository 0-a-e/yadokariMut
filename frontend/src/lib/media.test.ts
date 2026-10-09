import { describe, expect, it } from 'vitest';
import {
  DHASH_NEAR_THRESHOLD,
  hammingHex,
  isNearDuplicate,
  mediaImagePairs,
  mediaImageUrl,
} from './media.ts';
import type { MediaImageLike } from './media.ts';

describe('mediaImageUrl', () => {
  it('media_id があればオリジナル配信 URL を返す', () => {
    expect(mediaImageUrl({ media_id: 42 })).toBe('/api/media/42');
  });

  it('variant=thumb は has_thumb=true のときだけ ?variant=thumb を付ける', () => {
    expect(mediaImageUrl({ media_id: 42, has_thumb: true }, 'thumb')).toBe(
      '/api/media/42?variant=thumb',
    );
    // 未生成(has_thumb false / null)はオリジナルへ倒す(404 回避)
    expect(mediaImageUrl({ media_id: 42, has_thumb: false }, 'thumb')).toBe('/api/media/42');
    expect(mediaImageUrl({ media_id: 42, has_thumb: null }, 'thumb')).toBe('/api/media/42');
    // オリジナル要求は has_thumb に依存しない
    expect(mediaImageUrl({ media_id: 42, has_thumb: true })).toBe('/api/media/42');
  });

  it('media_id が無い・null の行は null(呼び出し側で image_url へフォールバック)', () => {
    expect(mediaImageUrl({ image_url: 'https://ext.example/a.jpg' })).toBeNull();
    expect(mediaImageUrl({ media_id: null })).toBeNull();
  });
});

describe('hammingHex', () => {
  it('同一 dHash は距離 0', () => {
    expect(hammingHex('0123456789abcdef', '0123456789abcdef')).toBe(0);
  });

  it('1bit 差は距離 1・2bit 差は距離 2', () => {
    expect(hammingHex('0000000000000000', '0000000000000001')).toBe(1);
    expect(hammingHex('0000000000000000', '0000000000000003')).toBe(2);
  });

  it('全ビット反転(f×16 vs 0×16)は距離 64', () => {
    expect(hammingHex('f'.repeat(16), '0'.repeat(16))).toBe(64);
  });

  it('長さ不一致は比較不能(Number.MAX_SAFE_INTEGER)', () => {
    expect(hammingHex('abcd', 'abcdef')).toBe(Number.MAX_SAFE_INTEGER);
  });

  it('16 進として不正な文字列も比較不能', () => {
    expect(hammingHex('zzzzzzzzzzzzzzzz', '0000000000000000')).toBe(
      Number.MAX_SAFE_INTEGER,
    );
  });
});

describe('isNearDuplicate', () => {
  const base = '0000000000000000';

  it('両者非 null かつ距離 <= しきい値(=8)は true', () => {
    expect(isNearDuplicate(base, '0000000000000003')).toBe(true); // 距離 2
    // しきい値ちょうど(下位 8 ビット差)
    expect(isNearDuplicate(base, '00000000000000ff')).toBe(true);
    expect(DHASH_NEAR_THRESHOLD).toBe(8);
  });

  it('距離がしきい値を超える別写真(距離 28 相当)は false', () => {
    expect(isNearDuplicate(base, '000000000fffffff')).toBe(false); // 28bit 差
  });

  it('null / undefined は近重複扱いしない(代表写真 thumbnail_url 等)', () => {
    expect(isNearDuplicate(base, null)).toBe(false);
    expect(isNearDuplicate(undefined, base)).toBe(false);
    expect(isNearDuplicate(null, null)).toBe(false);
  });
});

describe('mediaImagePairs', () => {
  it('媒体 URL の thumb/full ペアを作り、media_id 無しは image_url へフォールバックする', () => {
    const rows: MediaImageLike[] = [
      { image_url: 'https://ext.example/a.jpg', media_id: 7, has_thumb: true },
      { image_url: 'https://ext.example/b.jpg', media_id: 8, has_thumb: false },
      { image_url: 'https://ext.example/c.jpg', media_id: null },
    ];
    expect(mediaImagePairs(rows)).toEqual([
      { thumbUrl: '/api/media/7?variant=thumb', fullUrl: '/api/media/7' },
      { thumbUrl: '/api/media/8', fullUrl: '/api/media/8' },
      { thumbUrl: 'https://ext.example/c.jpg', fullUrl: 'https://ext.example/c.jpg' },
    ]);
  });

  it('URL を持たない行は落とす', () => {
    expect(mediaImagePairs([{ media_id: null, image_url: null }])).toEqual([]);
    // media_id のみでも配信可能(thumb は variant なしへ倒す)
    expect(mediaImagePairs([{ media_id: 3, has_thumb: null }])).toEqual([
      { thumbUrl: '/api/media/3', fullUrl: '/api/media/3' },
    ]);
  });
});
