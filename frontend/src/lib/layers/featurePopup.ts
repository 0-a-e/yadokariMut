import type { FeaturePopupDef, FeaturePopupField } from './types.ts';

/**
 * ベクタフィーチャのクリック属性ポップアップ(featurePopup)の組み立て。
 *
 * VectorEngine は GL canvas が pointer-events:none のため MapLibre の
 * イベントを直接拾えない。代わりに Leaflet 側の map click から
 * queryRenderedFeatures を呼び、ヒットしたフィーチャをこの純関数で
 * 表示HTMLへ落とす(oshima アダプタのポップアップ生成と同じ方針)。
 */

/** VectorEngine が GL上レイヤに付与するid接頭辞(addEntry の名前空間) */
const GL_LAYER_PREFIX = 'gl:';

/** GL上のレイヤid(`gl:{catalogId}:{index}`)から catalogId を取り出す */
export function catalogIdFromGlLayerId(layerId: string): string | null {
  if (!layerId.startsWith(GL_LAYER_PREFIX)) return null;
  const rest = layerId.slice(GL_LAYER_PREFIX.length);
  const last = rest.lastIndexOf(':');
  if (last <= 0) return null;
  return rest.slice(0, last);
}

/** 属性値の整形(featurePopup.fields[].format) */
export function formatPopupValue(value: unknown, format: FeaturePopupField['format']): string {
  if (value === undefined || value === null) return '';
  switch (format) {
    case 'int':
    case 'jpy-m2': {
      // 数値整形系: 非finite数(欠損相当)は空文字、文字列はそのまま通す(属性型の揺れ対策)
      if (typeof value === 'number') {
        if (!Number.isFinite(value)) return '';
        return format === 'jpy-m2' ? `${value.toLocaleString()}円/m²` : value.toLocaleString();
      }
      return typeof value === 'string' ? value : '';
    }
    default:
      return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case '&':
        return '&amp;';
      case '<':
        return '&lt;';
      case '>':
        return '&gt;';
      case '"':
        return '&quot;';
      default:
        return '&#39;';
    }
  });
}

// 色とフォントはCSS変数経由でアプリテーマに追従する(ポップアップDOMは
// #map 内にマウントされるため :root の変数が解決される)
const POPUP_STYLE = [
  'min-width:180px',
  'font-size:calc(12px * var(--font-scale))',
  'line-height:1.5',
  'color:inherit',
].join(';');

/**
 * featurePopup 定義とフィーチャ属性からポップアップHTMLを組み立てる。
 * タイトル(titleKey)は失われても本体を表示する(行は fields 順)。
 * 属性値は外部データのため必ずエスケープする。
 */
export function buildFeaturePopupHtml(
  def: FeaturePopupDef,
  properties: Record<string, unknown>,
): string {
  const rows: string[] = [];
  const titleRaw = def.titleKey !== undefined ? properties[def.titleKey] : undefined;
  if (titleRaw !== undefined && titleRaw !== null && titleRaw !== '') {
    rows.push(
      `<div style="font-weight:700;margin-bottom:2px;">${escapeHtml(formatPopupValue(titleRaw, 'plain'))}</div>`,
    );
  }
  for (const field of def.fields) {
    const value = formatPopupValue(properties[field.key], field.format);
    if (value === '') continue;
    rows.push(
      `<div><span style="color:var(--text-muted);">${escapeHtml(field.label)}: </span>${escapeHtml(value)}</div>`,
    );
  }
  return `<div style="${POPUP_STYLE}">${rows.join('')}</div>`;
}
