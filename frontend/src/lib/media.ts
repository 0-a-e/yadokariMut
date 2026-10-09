/**
 * メディアストア(rustfs)配信 URL と dHash 近重複判定の共通層
 * (docs/media-storage-rustfs-plan.md §2.7/§2.8)。
 *
 * BE の画像行(PropertyImageInfo)は media_id / dhash / has_thumb を追加搭載する。
 * 保存済みメディアは GET /api/media/{id}(オリジナル)・?variant=thumb(640px WebP・
 * has_thumb=true 時のみ)で取得でき、同一クラスタ(同一写真の再エンコード/サイズ違い)は
 * 同じ media_id に集約済み。media_id を持たない行(バックフィル未了・機能無効)は
 * 呼び出し側が従来どおり image_url(外部 URL)へフォールバックする。
 *
 * schema.d.ts 再生成前にコンパイルできるよう、行の形は構造型でローカル定義する。
 */

/** 画像行のうち本層が読むフィールド(PropertyImageInfo の media 拡張を構造的に受ける) */
export interface MediaImageLike {
  image_url?: string | null;
  media_id?: number | null;
  /** 16 進 16 桁の dHash(BE クラスタ判定と同一定数) */
  dhash?: string | null;
  /** thumb バリアント(640px WebP)が保存済みか */
  has_thumb?: boolean | null;
}

/**
 * dHash 近重複しきい値(64bit 中のハミング距離)。BE 正本と同値
 * (docs §2.7 実測: 同一写真の変異=0〜2 / 別写真=28 以上 → 単一しきい値 8 で確定)。
 */
export const DHASH_NEAR_THRESHOLD = 8;

/** カルーセル用サムネイル variant が存在するときに使うクエリ */
const THUMB_VARIANT_QUERY = '?variant=thumb';

/**
 * 画像行 → 配信 URL。media_id があればメディアストア配信 URL、無ければ null
 * (呼び出し側は image_url へフォールバックする)。
 *
 * variant='thumb' は has_thumb=true のときだけ ?variant=thumb を付ける
 * (未生成のメディアに variant を要求して 404 にしない)。
 */
export function mediaImageUrl(
  img: MediaImageLike,
  variant?: 'thumb',
): string | null {
  if (img.media_id == null) return null;
  const base = `/api/media/${img.media_id}`;
  return variant === 'thumb' && img.has_thumb === true
    ? `${base}${THUMB_VARIANT_QUERY}`
    : base;
}

/** カルーセル(thumb 優先)とライトボックス(オリジナル優先)で使う URL ペア */
export interface MediaImagePair {
  /** カルーセル・サムネイル列用(media_id が無ければ image_url) */
  thumbUrl: string;
  /** ライトボックス用オリジナル(media_id が無ければ image_url) */
  fullUrl: string;
}

/**
 * 画像行列 → URL ペア列。URL を持たない行(media_id も image_url も null)は落とす。
 * カルーセル/ライトボックスが同一の URL 列を共有している呼び出し元は、
 * 本関数の結果から thumb/full を取り出して渡す。
 */
export function mediaImagePairs(
  imgs: readonly MediaImageLike[],
): MediaImagePair[] {
  const pairs: MediaImagePair[] = [];
  for (const img of imgs) {
    const fullUrl = mediaImageUrl(img) ?? img.image_url;
    if (!fullUrl) continue;
    pairs.push({ thumbUrl: mediaImageUrl(img, 'thumb') ?? fullUrl, fullUrl });
  }
  return pairs;
}

/**
 * 16 進 64bit 文字列同士のハミング距離(BigInt xor + popcount)。
 * 長さ不一致・16 進として不正な入力は「比較不能」を表す Number.MAX_SAFE_INTEGER。
 */
export function hammingHex(a: string, b: string): number {
  if (a.length !== b.length) return Number.MAX_SAFE_INTEGER;
  let x: bigint;
  try {
    x = BigInt(`0x${a}`) ^ BigInt(`0x${b}`);
  } catch {
    return Number.MAX_SAFE_INTEGER;
  }
  let count = 0;
  while (x > 0n) {
    count += Number(x & 1n);
    x >>= 1n;
  }
  return count;
}

/**
 * dHash 近重複判定。両者が非 null かつハミング距離 <= DHASH_NEAR_THRESHOLD のとき true。
 * null(未計算・代表写真の thumbnail_url 由来)は近重複扱いしない。
 */
export function isNearDuplicate(
  a?: string | null,
  b?: string | null,
): boolean {
  if (!a || !b) return false;
  return hammingHex(a, b) <= DHASH_NEAR_THRESHOLD;
}
