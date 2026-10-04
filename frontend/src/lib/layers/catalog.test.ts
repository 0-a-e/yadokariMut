import { describe, expect, it, vi } from 'vitest';
import { LAYER_CATALOG } from './catalog.ts';
import { getAdapter } from './adapters/index.ts';
import { LAYER_TAGS, LAYER_TAG_LABELS } from './types.ts';

// environment: 'node' では leaflet がモジュールスコープの window 参照で
// import に失敗するためモックする(adapters/ の登録有無だけを検証するので
// 実装は不要。oshima.ts がモジュールスコープで使う L.Layer / L.divIcon のみ用意)
vi.mock('leaflet', () => {
  class Layer {}
  return {
    default: {
      Layer,
      divIcon: () => ({}),
    },
  };
});

/** CSS色としてパース可能な文字列か(hex / rgb(a) / hsl(a) / 色名) */
function isCssColor(value: string): boolean {
  const hex = /^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
  const functional =
    /^(?:rgb|rgba|hsl|hsla)\(\s*[-\d.]+%?(?:\s*,\s*[-\d.]+%?){2,3}\s*\)$/i;
  const named = /^[a-z]+$/i;
  return hex.test(value) || functional.test(value) || named.test(value);
}

describe('LAYER_CATALOG: エントリ整合性', () => {
  it('id が重複しない', () => {
    const ids = LAYER_CATALOG.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('必須フィールド(name, tags, adapter, attribution)が全エントリにある', () => {
    for (const entry of LAYER_CATALOG) {
      expect(entry.name, `${entry.id}: name`).toBeTruthy();
      expect(entry.tags.length, `${entry.id}: tags`).toBeGreaterThan(0);
      expect(entry.adapter, `${entry.id}: adapter`).toBeTruthy();
      expect(entry.attribution, `${entry.id}: attribution`).toBeTruthy();
    }
  });

  it('タグがすべて LAYER_TAGS に登録済み', () => {
    const known = new Set(LAYER_TAGS.map((t) => t.id));
    for (const entry of LAYER_CATALOG) {
      for (const tag of entry.tags) {
        expect(known.has(tag), `${entry.id}: 未知のタグ ${tag}`).toBe(true);
      }
    }
  });
});

describe('LAYER_CATALOG: アダプタごとの必須項目', () => {
  it("adapter === 'maplibre' ⇒ vector があり sources/layers が空でない", () => {
    const vectorEntries = LAYER_CATALOG.filter((e) => e.adapter === 'maplibre');
    expect(vectorEntries.length).toBeGreaterThan(0);
    for (const entry of vectorEntries) {
      expect(entry.vector, `${entry.id}: vector`).toBeDefined();
      expect(Object.keys(entry.vector!.sources).length, `${entry.id}: sources`).toBeGreaterThan(0);
      expect(entry.vector!.layers.length, `${entry.id}: layers`).toBeGreaterThan(0);
      for (const [id, source] of Object.entries(entry.vector!.sources)) {
        expect(source.type, `${entry.id}: sources.${id}.type`).toBe('vector');
        expect(source.tiles.length, `${entry.id}: sources.${id}.tiles`).toBeGreaterThan(0);
        for (const tile of source.tiles) {
          expect(tile, `${entry.id}: sources.${id}.tiles`).toBeTruthy();
        }
      }
      for (const layer of entry.vector!.layers) {
        expect(
          typeof (layer as { source?: unknown }).source === 'string' ||
            (layer as { source?: unknown }).source === undefined,
          `${entry.id}: layer.source`,
        ).toBe(true);
      }
    }
  });

  it("adapter !== 'maplibre' ⇒ urlTemplate がある(oshima を除く)", () => {
    for (const entry of LAYER_CATALOG.filter((e) => e.adapter !== 'maplibre')) {
      if (entry.adapter === 'oshima') continue;
      expect(entry.urlTemplate, `${entry.id}: urlTemplate`).toBeTruthy();
    }
  });
});

describe('LAYER_CATALOG: 凡例', () => {
  const entriesWithLegend = LAYER_CATALOG.filter((e) => e.legend !== undefined);

  it('legend は空でない配列(少なくとも1エントリが持つ)', () => {
    expect(entriesWithLegend.length).toBeGreaterThan(0);
    for (const entry of entriesWithLegend) {
      expect(entry.legend!.length, `${entry.id}: legend`).toBeGreaterThan(0);
    }
  });

  it('legend の color はCSS色としてパース可能・label は非空', () => {
    for (const entry of entriesWithLegend) {
      for (const item of entry.legend!) {
        expect(typeof item.color, `${entry.id}: legend.color`).toBe('string');
        expect(isCssColor(item.color), `${entry.id}: legend.color=${item.color}`).toBe(true);
        expect(item.label.trim(), `${entry.id}: legend.label`).toBeTruthy();
      }
    }
  });
});

describe('タグラベル', () => {
  it('LAYER_TAG_LABELS が LAYER_TAGS を過不足なく網羅する', () => {
    for (const tag of LAYER_TAGS) {
      expect(LAYER_TAG_LABELS[tag.id], tag.id).toBe(tag.label);
    }
    expect(Object.keys(LAYER_TAG_LABELS).sort()).toEqual(
      LAYER_TAGS.map((t) => t.id).sort(),
    );
  });
});

describe('アダプタ登録(未登録アダプタが無音で壊れる弱点の回帰テスト)', () => {
  it('LAYER_CATALOG 全エントリの adapter が getAdapter で取得できる', () => {
    for (const entry of LAYER_CATALOG) {
      const adapter = getAdapter(entry.adapter);
      expect(adapter, `${entry.id}: adapter '${entry.adapter}' が未登録`).toBeDefined();
      expect(typeof adapter!.create, `${entry.id}: adapter.create`).toBe('function');
    }
  });
});
