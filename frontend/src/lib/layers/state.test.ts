import { describe, expect, it } from 'vitest';
import {
  addGroup,
  addLayer,
  assignLayerGroup,
  createDefaultLayerConfig,
  flattenOrderIds,
  flattenStack,
  loadLayerConfig,
  makeLayerActions,
  moveToGroup,
  removeGroup,
  removeLayer,
  removeFromGroup,
  reorderGroupMembers,
  reorderStack,
  saveLayerConfig,
  selectBase,
  setLayerOrder,
  setLayerVisible,
} from './state';
import type { LayerConfigState } from './types';
import { catalogById } from './catalog';

function withLayers(...ids: string[]): LayerConfigState {
  return {
    v: 2,
    stack: ids.map((id) => ({ kind: 'layer' as const, id, visible: true, opacity: 1 })),
    groups: [],
  };
}

describe('selectBase (上部タブのショートカット)', () => {
  it('既存ベースを除去し指定ベースを末尾(最下段)に置く', () => {
    const config = withLayers('relief', 'pale', 'hillshademap');
    const next = selectBase(config, 'std');
    expect(flattenOrderIds(next.stack)).toEqual(['relief', 'hillshademap', 'std']);
    expect(flattenStack(next.stack)[2]).toMatchObject({ visible: true, opacity: 1 });
  });

  it('ベースを2枚重ねない(排他はアクション層で保証)', () => {
    const next = selectBase(selectBase(withLayers('pale'), 'dark'), 'satellite');
    const bases = flattenStack(next.stack).filter((l) => catalogById.get(l.id)?.role === 'base');
    expect(bases.map((l) => l.id)).toEqual(['satellite']);
  });
});

describe('addLayer / removeLayer(デフォルト透明度)', () => {
  it('カタログのdefaultOpacityが初期透明度になる(flood_l2=0.6, swale=0.3)', () => {
    const next = addLayer(withLayers('pale'), 'flood_l2');
    expect(next.stack[0]).toMatchObject({ kind: 'layer', id: 'flood_l2', opacity: 0.6 });
    const next2 = addLayer(next, 'swale');
    expect(next2.stack[0]).toMatchObject({ id: 'swale', opacity: 0.3 });
  });

  it('災害・磁気・火山の既定透明度(afm=0.4, 磁気5枚=0.25, vlcd=0.45)', () => {
    let config = addLayer(withLayers('pale'), 'afm');
    expect(config.stack[0]).toMatchObject({ id: 'afm', opacity: 0.4 });
    for (const suf of ['d', 'i', 'f', 'h', 'z'] as const) {
      config = addLayer(config, `jikizu2020_chijiki_${suf}`);
      expect(config.stack[0]).toMatchObject({
        id: `jikizu2020_chijiki_${suf}`,
        opacity: 0.25,
      });
    }
    config = addLayer(config, 'vlcd');
    expect(config.stack[0]).toMatchObject({ id: 'vlcd', opacity: 0.45 });
  });

  it('明示プロバイダがカタログ値を上書きする(feSettings由来)', () => {
    const next = addLayer(withLayers('pale'), 'flood_l2', () => 0.8);
    expect(next.stack[0]).toMatchObject({ id: 'flood_l2', opacity: 0.8 });
  });

  it('defaultOpacity未設定レイヤは1。二重追加・カタログ外idは無視', () => {
    const config = withLayers('pale');
    expect(addLayer(config, 'relief').stack[0]).toMatchObject({ opacity: 1 });
    const first = addLayer(config, 'relief');
    expect(addLayer(first, 'relief')).toBe(first);
    expect(addLayer(config, 'no-such-layer')).toBe(config);
  });

  it('ベースの追加は排他selectBaseへ、グループ内レイヤも削除できる', () => {
    let config = addLayer(withLayers('pale'), 'relief');
    config = addGroup(config, 'g');
    const gid = config.groups[0].id;
    config = assignLayerGroup(config, 'relief', gid);
    expect(config.stack.some((s) => s.kind === 'group' && s.members.length === 1)).toBe(true);
    const removed = removeLayer(config, 'relief');
    expect(flattenOrderIds(removed.stack)).toEqual(['pale']);
    // 空ブロックは残る(③のUIで表示)
    expect(removed.stack.some((s) => s.kind === 'group')).toBe(true);
  });
});

describe('グループ操作(v2ネストスタック)', () => {
  const setup = () => {
    let config = withLayers('relief', 'slopemap', 'hillshademap', 'pale');
    config = addGroup(config, '災害');
    return { config, gid: config.groups[0].id };
  };

  it('moveToGroup: ブロック錨は最初のメンバー投入位置。removeFromGroupはブロック直後へ', () => {
    let { config, gid } = setup();
    config = moveToGroup(config, 'slopemap', gid);
    config = moveToGroup(config, 'hillshademap', gid);
    // addGroupの空ブロックは末尾にあるため、メンバー加入後もブロック位置は末尾
    expect(flattenOrderIds(config.stack)).toEqual(['relief', 'pale', 'slopemap', 'hillshademap']);
    const block = config.stack.find((s) => s.kind === 'group');
    expect(block).toMatchObject({ kind: 'group', groupId: gid });
    if (block?.kind === 'group') {
      expect(block.members.map((m) => m.id)).toEqual(['slopemap', 'hillshademap']);
    }

    const out = removeFromGroup(config, 'slopemap');
    // 外れたレイヤはブロック直後のトップレベルへ
    expect(flattenOrderIds(out.stack)).toEqual(['relief', 'pale', 'hillshademap', 'slopemap']);
    expect(out.stack.some((s) => s.kind === 'layer' && s.id === 'slopemap')).toBe(true);
  });

  it('moveToGroup(index)で挿入位置指定・reorderGroupMembersで並べ替え', () => {
    let { config, gid } = setup();
    config = moveToGroup(config, 'relief', gid);
    config = moveToGroup(config, 'hillshademap', gid);
    config = moveToGroup(config, 'slopemap', gid, 0); // 先頭へ
    expect(flattenOrderIds(config.stack)).toEqual(['pale', 'slopemap', 'relief', 'hillshademap']);
    const block = config.stack.find((s) => s.kind === 'group');
    if (block?.kind === 'group') {
      const reordered = reorderGroupMembers(config, gid, [
        'hillshademap',
        'slopemap',
        'relief',
      ]);
      expect(flattenOrderIds(reordered.stack)).toEqual([
        'pale',
        'hillshademap',
        'slopemap',
        'relief',
      ]);
      // 過不足ある順序は拒否
      expect(reorderGroupMembers(config, gid, ['relief'])).toBe(config);
    }
  });

  it('ベースレイヤはグループ参加不可', () => {
    const { config, gid } = setup();
    expect(moveToGroup(config, 'pale', gid)).toBe(config);
  });

  it('removeGroupはメンバーをブロック位置に平坦化。未知グループは拒否', () => {
    let { config, gid } = setup();
    config = moveToGroup(config, 'relief', gid);
    config = moveToGroup(config, 'hillshademap', gid);
    const flat = removeGroup(config, gid);
    expect(flat.groups).toEqual([]);
    expect(flat.stack.map((s) => (s.kind === 'group' ? `g:${s.groupId}` : s.id))).toEqual([
      'slopemap',
      'pale',
      'relief',
      'hillshademap',
    ]);
    expect(moveToGroup(config, 'relief', 'g-unknown')).toBe(config);
  });

  it('reorderStack: トップレベル要素(layer id or groupId)の並べ替え', () => {
    let { config, gid } = setup();
    config = moveToGroup(config, 'relief', gid); // stack: [G(relief), slopemap, hillshademap, pale]
    const next = reorderStack(config, [gid, 'pale', 'slopemap', 'hillshademap']);
    expect(
      next.stack.map((s) => (s.kind === 'group' ? `g:${s.groupId}` : s.id)),
    ).toEqual([`g:${gid}`, 'pale', 'slopemap', 'hillshademap']);
    // 過不足は拒否
    expect(reorderStack(config, [gid, 'pale'])).toBe(config);
  });
});

describe('setLayerOrder(AI互換の平坦順序)', () => {
  it('グループはアンカー位置にブロック化。メンバーは新順序の相対順', () => {
    let config = withLayers('relief', 'slopemap', 'hillshademap', 'pale');
    config = addGroup(config, 'g');
    const gid = config.groups[0].id;
    config = moveToGroup(config, 'slopemap', gid);
    config = moveToGroup(config, 'hillshademap', gid);

    const next = setLayerOrder(config, ['pale', 'hillshademap', 'relief', 'slopemap']);
    // グループはアトミック: メンバーはアンカー位置に集約される
    expect(flattenOrderIds(next.stack)).toEqual([
      'pale',
      'hillshademap',
      'slopemap',
      'relief',
    ]);
    const block = next.stack.find((s) => s.kind === 'group');
    expect(block).toBeDefined();
    if (block?.kind === 'group') {
      expect(block.members.map((m) => m.id)).toEqual(['hillshademap', 'slopemap']);
    }
  });

  it('過不足・未知id・重複は破棄', () => {
    const config = withLayers('pale', 'relief');
    expect(setLayerOrder(config, ['pale'])).toBe(config);
    expect(setLayerOrder(config, ['pale', 'relief', 'oshima'])).toBe(config);
    expect(setLayerOrder(config, ['pale', 'pale'])).toBe(config);
  });
});

describe('setLayerVisible はグループ内レイヤにも効く', () => {
  it('memberのvisibleを変更', () => {
    let config = withLayers('pale', 'relief');
    config = addGroup(config, 'g');
    config = moveToGroup(config, 'relief', config.groups[0].id);
    const next = setLayerVisible(config, 'relief', false);
    const block = next.stack.find((s) => s.kind === 'group');
    if (block?.kind === 'group') {
      expect(block.members[0].visible).toBe(false);
    } else {
      throw new Error('block missing');
    }
  });
});

describe('永続化(v1→v2移行含む)', () => {
  it('localStorage無し環境(node)ではデフォルト設定を返す', () => {
    expect(loadLayerConfig()).toEqual(createDefaultLayerConfig());
  });

  it('v2の保存→読込はカタログ内idのみ復元し不正値を正規化', () => {
    const store = new Map<string, string>();
    const g = globalThis as { localStorage?: Storage };
    const backup = g.localStorage;
    g.localStorage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    } as Storage;
    try {
      let config = withLayers('pale', 'relief', 'flood_l2');
      config = addGroup(config, 'hazard');
      config = moveToGroup(config, 'flood_l2', config.groups[0].id);
      saveLayerConfig(config);
      const loaded = loadLayerConfig();
      expect(loaded.v).toBe(2);
      expect(flattenOrderIds(loaded.stack)).toEqual(['pale', 'relief', 'flood_l2']);
      expect(loaded.groups.map((x) => x.name)).toEqual(['hazard']);
    } finally {
      if (backup) g.localStorage = backup;
      else delete g.localStorage;
    }
  });

  it('v1形式(平坦layers+groupId)はv2へ移行される: グループは先頭メンバー位置にブロック化', () => {
    const store = new Map<string, string>();
    const g = globalThis as { localStorage?: Storage };
    const backup = g.localStorage;
    g.localStorage = {
      getItem: () =>
        JSON.stringify({
          v: 1,
          layers: [
            { id: 'relief', visible: true, opacity: 1, groupId: 'g1' },
            { id: 'pale', visible: true, opacity: 1 },
            { id: 'flood_l2', visible: true, opacity: 0.4, groupId: 'g1' },
            { id: 'gone-from-catalog', visible: true, opacity: 1 },
          ],
          groups: [{ id: 'g1', name: '災害', visible: true, opacity: 0.9, collapsed: false }],
        }),
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    } as Storage;
    try {
      const loaded = loadLayerConfig();
      expect(loaded.v).toBe(2);
      expect(
        loaded.stack.map((s) => (s.kind === 'group' ? `g:${s.groupId}` : s.id)),
      ).toEqual(['g:g1', 'pale']);
      const block = loaded.stack[0];
      if (block.kind === 'group') {
        expect(block.members.map((m) => m.id)).toEqual(['relief', 'flood_l2']);
        expect(block.members[1].opacity).toBe(0.4);
      }
      expect(loaded.groups[0]).toMatchObject({ id: 'g1', name: '災害', opacity: 0.9 });
    } finally {
      if (backup) g.localStorage = backup;
      else delete g.localStorage;
    }
  });

  it('壊れたJSONはデフォルト設定にフォールバック', () => {
    const g = globalThis as { localStorage?: Storage };
    const backup = g.localStorage;
    g.localStorage = {
      getItem: () => '{{{not json',
      setItem: () => {},
      removeItem: () => {},
    } as Storage;
    try {
      expect(loadLayerConfig()).toEqual(createDefaultLayerConfig());
    } finally {
      if (backup) g.localStorage = backup;
      else delete g.localStorage;
    }
  });
});

describe('makeLayerActions', () => {
  it('各アクションがcommit経由で状態を更新する', () => {
    let config = withLayers('pale');
    const actions = makeLayerActions((updater) => {
      config = updater(config);
    });
    actions.addLayer('relief');
    actions.selectBase('std');
    actions.setLayerVisible('relief', false);
    expect(flattenOrderIds(config.stack)).toEqual(['relief', 'std']);
    expect(flattenStack(config.stack)[0].visible).toBe(false);
  });
});
