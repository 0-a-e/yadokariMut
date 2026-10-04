import type { BaseLayerId, LayerConfigState, LayerGroup, LayerRuntime, StackItem } from './types.ts';
import { PROPERTIES_LAYER_ID } from './types.ts';
import { catalogById } from './catalog.ts';

const STORAGE_KEY = 'yadokari:layers';

/** 物件ピン(検索結果)レイヤの既定ランタイム(可視・不透明) */
export function createDefaultPropertiesRuntime(): LayerRuntime {
  return { id: PROPERTIES_LAYER_ID, visible: true, opacity: 1 };
}

export function createDefaultLayerConfig(): LayerConfigState {
  // 現行アプリの初期表示と同じく淡色ベース1枚
  return {
    v: 2,
    stack: [{ kind: 'layer', id: 'pale', visible: true, opacity: 1 }],
    groups: [],
    properties: createDefaultPropertiesRuntime(),
  };
}

// ─────────────────────────────────────────────
// 読み取りヘルパー
// ─────────────────────────────────────────────

const layerItem = (item: StackItem): item is { kind: 'layer' } & LayerRuntime =>
  item.kind === 'layer';

/** スタックを平坦なレイヤ列へ(グループはその位置に展開)。UIの旧layers互換ビュー */
export function flattenStack(stack: StackItem[]): Array<LayerRuntime & { groupId?: string }> {
  const out: Array<LayerRuntime & { groupId?: string }> = [];
  for (const item of stack) {
    if (layerItem(item)) out.push({ id: item.id, visible: item.visible, opacity: item.opacity });
    else for (const m of item.members) out.push({ ...m, groupId: item.groupId });
  }
  return out;
}

/** 全レイヤidのスタック順列(AI互換の setLayerOrder 入力)。空グループブロックは含まない */
export function flattenOrderIds(stack: StackItem[]): string[] {
  return flattenStack(stack).map((l) => l.id);
}

/**
 * 実効ランタイム列(スタック順=先頭が最前面)。グループメンバーはグループの
 * visible/opacity を反映した実効値に解決する(engine.sync のベクタ適用と同じ規則)。
 * 地図上凡例コントロールなど、表示中レイヤの列挙に使う。
 */
export function effectiveRuntimeList(
  config: LayerConfigState,
): Array<LayerRuntime & { groupId?: string }> {
  const groupById = new Map(config.groups.map((g) => [g.id, g]));
  return flattenStack(config.stack).map((layer) => {
    if (layer.groupId === undefined) return layer;
    const group = groupById.get(layer.groupId);
    return {
      ...layer,
      visible: layer.visible && group?.visible !== false,
      opacity: layer.opacity * (group?.opacity ?? 1),
    };
  });
}

const findLayerGroup = (stack: StackItem[], id: string): string | undefined => {
  for (const item of stack) {
    if (layerItem(item)) continue;
    if (item.members.some((m) => m.id === id)) return item.groupId;
  }
  return undefined;
};

const removeLayerFromStack = (stack: StackItem[], id: string): StackItem[] =>
  stack
    .filter((item) => !(layerItem(item) && item.id === id))
    .map((item) =>
      layerItem(item) ? item : { ...item, members: item.members.filter((m) => m.id !== id) },
    );

const clamp01 = (v: unknown): number =>
  typeof v === 'number' && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 1;

/** レイヤ追加時の初期透明度(カタログのデフォルト透明度 → 1)。AppからfeSettingsで上書き可能 */
export type InitialOpacityProvider = (id: string) => number;

const catalogInitialOpacity: InitialOpacityProvider = (id) => catalogById.get(id)?.defaultOpacity ?? 1;

/** DnD確定時の挿入位置指定(placeLayerの入力) */
export type DropPosition =
  | { kind: 'top'; index: number }
  | { kind: 'group'; groupId: string; index: number };

/**
 * レイヤを指定位置へ一括移動/挿入(無効↔有効のDnD確定用)。
 * position.index は「移動前の表示座標系」での挿入位置を指す(over行の直前=その行の
 * index、直後=+1)。同一リスト内の移動ではメンバー除去で座標がずれるため、ここで調整する。
 * - 無効レイヤのidなら新規追加(visible=true、既定透明度)、有効レイヤならそのまま移動
 * - ベースは最下層固定のため本関数では扱わない(切替はselectBase専用)。top indexは
 *   ベース行の直前までにクランプされる
 * - グループ未作成なら末尾にブロックを作る。存在しないid/グループはconfig不変
 */
export function placeLayer(
  config: LayerConfigState,
  id: string,
  position: DropPosition,
  initialOpacity: InitialOpacityProvider = catalogInitialOpacity,
): LayerConfigState {
  const entry = catalogById.get(id);
  if (!entry || entry.role === 'base') return config;

  // 移動元の現在位置(除去前座標系)。index調整に使用
  const fromTopIndex = config.stack.findIndex((s) => layerItem(s) && s.id === id);
  let fromMemberIndex = -1;
  let fromGroupId: string | undefined;
  if (fromTopIndex < 0 && flattenOrderIds(config.stack).includes(id)) {
    for (const item of config.stack) {
      if (layerItem(item)) continue;
      const i = item.members.findIndex((m) => m.id === id);
      if (i >= 0) {
        fromMemberIndex = i;
        fromGroupId = item.groupId;
        break;
      }
    }
  }
  const wasEnabled = fromTopIndex >= 0 || fromMemberIndex >= 0;

  const member: LayerRuntime = wasEnabled
    ? { ...flattenStack(config.stack).find((l) => l.id === id)! }
    : { id, visible: true, opacity: initialOpacity(id) };
  const stack = wasEnabled ? removeLayerFromStack(config.stack, id) : config.stack;

  if (position.kind === 'top') {
    // ベースは最下層固定: 挿入位置はベース行の直前まで
    const baseIndex = stack.findIndex(
      (item) => layerItem(item) && catalogById.get(item.id)?.role === 'base',
    );
    const maxIndex = baseIndex >= 0 ? baseIndex : stack.length;
    const at =
      fromTopIndex >= 0 && position.index > fromTopIndex ? position.index - 1 : position.index;
    const clamped = Math.min(Math.max(at, 0), maxIndex);
    const next = [...stack];
    next.splice(clamped, 0, { kind: 'layer', ...member });
    return { ...config, stack: next };
  }

  if (!config.groups.some((g) => g.id === position.groupId)) return config;
  const blockIndex = stack.findIndex(
    (item) => !layerItem(item) && item.groupId === position.groupId,
  );
  if (blockIndex < 0) {
    return {
      ...config,
      stack: [...stack, { kind: 'group', groupId: position.groupId, members: [member] }],
    };
  }
  const block = stack[blockIndex];
  if (layerItem(block)) return config;
  const members = [...block.members];
  // 同一グループ内の移動ではメンバー除去で挿入点が1つずれる
  const from = fromGroupId === position.groupId ? fromMemberIndex : -1;
  const at = from >= 0 && position.index > from ? position.index - 1 : position.index;
  const clamped = Math.min(Math.max(at, 0), members.length);
  members.splice(clamped, 0, member);
  return {
    ...config,
    stack: stack.map((item, i) => (i === blockIndex ? { ...block, members } : item)),
  };
}

// ─────────────────────────────────────────────
// 純粋操作(単体テスト対象)。常に新しいオブジェクトを返す
// ─────────────────────────────────────────────

/**
 * ベースマップ切替(上部タブの正体)。
 * role:'base' のレイヤを全て除去し、指定ベースを末尾(最下段)に追加する。
 * 排他はここ(reducerではなくアクション層)で保証する。
 */
export function selectBase(
  config: LayerConfigState,
  id: BaseLayerId,
  initialOpacity: InitialOpacityProvider = catalogInitialOpacity,
): LayerConfigState {
  const stack = config.stack.filter(
    (item) => !(layerItem(item) && catalogById.get(item.id)?.role === 'base'),
  );
  return {
    ...config,
    stack: [...stack, { kind: 'layer', id, visible: true, opacity: initialOpacity(id) }],
  };
}

/** レイヤ有効化。新規レイヤは先頭(最前面)。ベースは排他付きで末尾に置く */
export function addLayer(
  config: LayerConfigState,
  id: string,
  initialOpacity: InitialOpacityProvider = catalogInitialOpacity,
): LayerConfigState {
  const entry = catalogById.get(id);
  if (!entry) return config;
  if (flattenOrderIds(config.stack).includes(id)) return config;
  if (entry.role === 'base') return selectBase(config, id as BaseLayerId, initialOpacity);
  return {
    ...config,
    stack: [{ kind: 'layer', id, visible: true, opacity: initialOpacity(id) }, ...config.stack],
  };
}

export function removeLayer(config: LayerConfigState, id: string): LayerConfigState {
  return { ...config, stack: removeLayerFromStack(config.stack, id) };
}

export function setLayerVisible(
  config: LayerConfigState,
  id: string,
  visible: boolean,
): LayerConfigState {
  return {
    ...config,
    stack: config.stack.map((item) =>
      layerItem(item)
        ? item.id === id
          ? { ...item, visible }
          : item
        : {
            ...item,
            members: item.members.map((m) => (m.id === id ? { ...m, visible } : m)),
          },
    ),
  };
}

export function setLayerOpacity(
  config: LayerConfigState,
  id: string,
  opacity: number,
): LayerConfigState {
  const clamped = Math.min(1, Math.max(0, opacity));
  return {
    ...config,
    stack: config.stack.map((item) =>
      layerItem(item)
        ? item.id === id
          ? { ...item, opacity: clamped }
          : item
        : {
            ...item,
            members: item.members.map((m) => (m.id === id ? { ...m, opacity: clamped } : m)),
          },
    ),
  };
}

/** トップレベル要素(layer id or groupId)の並べ替え。過不足/重複なしの順序のみ受理 */
export function reorderStack(config: LayerConfigState, itemIds: string[]): LayerConfigState {
  const current = config.stack.map((item) => (layerItem(item) ? item.id : item.groupId));
  const currentSet = new Set(current);
  const nextSet = new Set(itemIds);
  if (
    itemIds.length !== current.length ||
    nextSet.size !== itemIds.length ||
    itemIds.some((x) => !currentSet.has(x))
  ) {
    return config;
  }
  const byId = new Map(config.stack.map((item) => [layerItem(item) ? item.id : item.groupId, item]));
  return { ...config, stack: itemIds.map((x) => byId.get(x)!) };
}

/**
 * レイヤをグループへ移動(index省略時は末尾)。
 * baseレイヤはグループ参加不可。グループのブロックが未作成なら末尾に作る。
 */
export function moveToGroup(
  config: LayerConfigState,
  id: string,
  groupId: string,
  index?: number,
): LayerConfigState {
  if (!config.groups.some((g) => g.id === groupId)) return config;
  if (catalogById.get(id)?.role === 'base') return config;
  if (!flattenOrderIds(config.stack).includes(id)) return config;

  const member: LayerRuntime = { ...flattenStack(config.stack).find((l) => l.id === id)! };
  let stack = removeLayerFromStack(config.stack, id);

  const blockIndex = stack.findIndex(
    (item) => !layerItem(item) && item.groupId === groupId,
  );
  if (blockIndex >= 0) {
    const block = stack[blockIndex];
    if (!layerItem(block)) {
      const members = [...block.members];
      const at = index == null ? members.length : Math.min(Math.max(index, 0), members.length);
      members.splice(at, 0, member);
      stack = stack.map((item, i) => (i === blockIndex ? { ...block, members } : item));
    }
  } else {
    stack = [...stack, { kind: 'group', groupId, members: [member] }];
  }
  return { ...config, stack };
}

/** レイヤをグループから外し、そのグループブロックの直後にトップレベルで置く */
export function removeFromGroup(config: LayerConfigState, id: string): LayerConfigState {
  const groupId = findLayerGroup(config.stack, id);
  if (!groupId) return config;
  const member: LayerRuntime = { ...flattenStack(config.stack).find((l) => l.id === id)! };
  const stack = removeLayerFromStack(config.stack, id);
  const blockIndex = stack.findIndex((item) => !layerItem(item) && item.groupId === groupId);
  if (blockIndex < 0) return { ...config, stack: [ { kind: 'layer', ...member }, ...stack ] };
  const next = [...stack];
  next.splice(blockIndex + 1, 0, { kind: 'layer', ...member });
  return { ...config, stack: next };
}

/** グループ内メンバーの並べ替え(過不足なしの順序のみ受理) */
export function reorderGroupMembers(
  config: LayerConfigState,
  groupId: string,
  memberIds: string[],
): LayerConfigState {
  const block = config.stack.find(
    (item) => !layerItem(item) && item.groupId === groupId,
  );
  if (!block || layerItem(block)) return config;
  const currentIds = block.members.map((m) => m.id);
  const currentSet = new Set(currentIds);
  const nextSet = new Set(memberIds);
  if (
    memberIds.length !== currentIds.length ||
    nextSet.size !== memberIds.length ||
    memberIds.some((x) => !currentSet.has(x))
  ) {
    return config;
  }
  const byId = new Map(block.members.map((m) => [m.id, m]));
  return {
    ...config,
    stack: config.stack.map((item) =>
      !layerItem(item) && item.groupId === groupId
        ? { ...item, members: memberIds.map((x) => byId.get(x)!) }
        : item,
    ),
  };
}

let groupSeq = 0;

/** グループ作成(メタデータ+末尾の空ブロック) */
export function addGroup(config: LayerConfigState, name: string): LayerConfigState {
  const id = `g${Date.now().toString(36)}${(groupSeq++).toString(36)}${Math.random()
    .toString(36)
    .slice(2, 6)}`;
  const group: LayerGroup = {
    id,
    name: name.trim() || `グループ ${config.groups.length + 1}`,
    visible: true,
    opacity: 1,
    collapsed: false,
  };
  return {
    ...config,
    groups: [...config.groups, group],
    stack: [...config.stack, { kind: 'group', groupId: id, members: [] }],
  };
}

/** グループ削除。メンバーはブロック位置に平坦化して残る */
export function removeGroup(config: LayerConfigState, groupId: string): LayerConfigState {
  const stack: StackItem[] = [];
  for (const item of config.stack) {
    if (layerItem(item) || item.groupId !== groupId) stack.push(item);
    else stack.push(...item.members.map((m) => ({ kind: 'layer' as const, ...m })));
  }
  return { ...config, stack, groups: config.groups.filter((g) => g.id !== groupId) };
}

export function renameGroup(
  config: LayerConfigState,
  groupId: string,
  name: string,
): LayerConfigState {
  return {
    ...config,
    groups: config.groups.map((g) => (g.id === groupId ? { ...g, name } : g)),
  };
}

export function setGroupVisible(
  config: LayerConfigState,
  groupId: string,
  visible: boolean,
): LayerConfigState {
  return {
    ...config,
    groups: config.groups.map((g) => (g.id === groupId ? { ...g, visible } : g)),
  };
}

export function setGroupOpacity(
  config: LayerConfigState,
  groupId: string,
  opacity: number,
): LayerConfigState {
  const clamped = Math.min(1, Math.max(0, opacity));
  return {
    ...config,
    groups: config.groups.map((g) => (g.id === groupId ? { ...g, opacity: clamped } : g)),
  };
}

/** グループ割当の統合入口(select互換): groupId=null で外す */
export function assignLayerGroup(
  config: LayerConfigState,
  id: string,
  groupId: string | null,
): LayerConfigState {
  return groupId === null ? removeFromGroup(config, id) : moveToGroup(config, id, groupId);
}

// ── 物件ピンレイヤ(スタック外の最前面固定特殊行) ──

export function setPropertiesVisible(
  config: LayerConfigState,
  visible: boolean,
): LayerConfigState {
  return { ...config, properties: { ...config.properties, visible } };
}

export function setPropertiesOpacity(
  config: LayerConfigState,
  opacity: number,
): LayerConfigState {
  const clamped = Math.min(1, Math.max(0, opacity));
  return { ...config, properties: { ...config.properties, opacity: clamped } };
}

/**
 * AI互換の全レイヤ順序指定: 平坦なid列(グループは先頭メンバーの位置にブロック)。
 * グループのアンカー=新順序中の当該グループメンバーの最小index。メンバーは新順序内の
 * 相対順でブロック内に並ぶ。空グループブロックは末尾に維持される。
 */
export function setLayerOrder(config: LayerConfigState, ids: string[]): LayerConfigState {
  const currentIds = flattenOrderIds(config.stack);
  const currentSet = new Set(currentIds);
  const nextSet = new Set(ids);
  if (
    ids.length !== currentSet.size ||
    nextSet.size !== ids.length ||
    ids.some((x) => !currentSet.has(x))
  ) {
    return config;
  }

  const groupOf = new Map<string, string>();
  for (const item of config.stack) {
    if (!layerItem(item)) for (const m of item.members) groupOf.set(m.id, item.groupId);
  }
  const indexIn = new Map(ids.map((id, i) => [id, i]));
  const anchorOf = new Map<string, number>();
  for (const [layerId, gid] of groupOf) {
    const i = indexIn.get(layerId) ?? Infinity;
    anchorOf.set(gid, Math.min(anchorOf.get(gid) ?? Infinity, i));
  }

  const layersById = new Map(
    flattenStack(config.stack).map((l) => [l.id, { id: l.id, visible: l.visible, opacity: l.opacity }]),
  );
  const stack: StackItem[] = [];
  const emittedGroups = new Set<string>();
  for (const id of ids) {
    const gid = groupOf.get(id);
    if (gid == null) {
      stack.push({ kind: 'layer', ...layersById.get(id)! });
      continue;
    }
    if (emittedGroups.has(gid)) continue;
    emittedGroups.add(gid);
    const members = ids
      .filter((x) => groupOf.get(x) === gid)
      .map((x) => layersById.get(x)!)
      .sort((a, b) => (indexIn.get(a.id) ?? 0) - (indexIn.get(b.id) ?? 0));
    stack.push({ kind: 'group', groupId: gid, members });
  }
  // 空グループブロックは末尾へ(相対順維持)
  for (const item of config.stack) {
    if (!layerItem(item) && !emittedGroups.has(item.groupId)) stack.push(item);
  }
  return { ...config, stack };
}

// ─────────────────────────────────────────────
// アクション束(Appで makeLayerActions((u) => setConfig(c => u(c))) のように括る)
// ─────────────────────────────────────────────

export interface LayerActions {
  selectBase(id: BaseLayerId): void;
  addLayer(id: string): void;
  removeLayer(id: string): void;
  setLayerVisible(id: string, visible: boolean): void;
  setLayerOpacity(id: string, opacity: number): void;
  setLayerOrder(ids: string[]): void;
  /** トップレベル要素(レイヤid or グループid)の並べ替え(v2) */
  reorderStack(itemIds: string[]): void;
  /** DnD確定用の位置指定一括挿入/移動(無効↔有効、グループ参加含む) */
  placeLayer(id: string, position: DropPosition): void;
  moveToGroup(id: string, groupId: string, index?: number): void;
  removeFromGroup(id: string): void;
  reorderGroupMembers(groupId: string, memberIds: string[]): void;
  addGroup(name: string): void;
  removeGroup(groupId: string): void;
  renameGroup(groupId: string, name: string): void;
  setGroupVisible(groupId: string, visible: boolean): void;
  setGroupOpacity(groupId: string, opacity: number): void;
  assignLayerGroup(id: string, groupId: string | null): void;
  /** 物件ピンレイヤ(最前面固定特殊行)の表示/非表示 */
  setPropertiesVisible(visible: boolean): void;
  /** 物件ピンレイヤの不透明度 */
  setPropertiesOpacity(opacity: number): void;
}

type Commit = (updater: (config: LayerConfigState) => LayerConfigState) => void;

export function makeLayerActions(
  commit: Commit,
  initialOpacity: InitialOpacityProvider = catalogInitialOpacity,
): LayerActions {
  return {
    selectBase: (id) => commit((c) => selectBase(c, id, initialOpacity)),
    addLayer: (id) => commit((c) => addLayer(c, id, initialOpacity)),
    removeLayer: (id) => commit((c) => removeLayer(c, id)),
    setLayerVisible: (id, visible) => commit((c) => setLayerVisible(c, id, visible)),
    setLayerOpacity: (id, opacity) => commit((c) => setLayerOpacity(c, id, opacity)),
    setLayerOrder: (ids) => commit((c) => setLayerOrder(c, ids)),
    reorderStack: (itemIds) => commit((c) => reorderStack(c, itemIds)),
    placeLayer: (id, position) => commit((c) => placeLayer(c, id, position, initialOpacity)),
    moveToGroup: (id, groupId, index) => commit((c) => moveToGroup(c, id, groupId, index)),
    removeFromGroup: (id) => commit((c) => removeFromGroup(c, id)),
    reorderGroupMembers: (groupId, memberIds) =>
      commit((c) => reorderGroupMembers(c, groupId, memberIds)),
    addGroup: (name) => commit((c) => addGroup(c, name)),
    removeGroup: (groupId) => commit((c) => removeGroup(c, groupId)),
    renameGroup: (groupId, name) => commit((c) => renameGroup(c, groupId, name)),
    setGroupVisible: (groupId, visible) => commit((c) => setGroupVisible(c, groupId, visible)),
    setGroupOpacity: (groupId, opacity) => commit((c) => setGroupOpacity(c, groupId, opacity)),
    assignLayerGroup: (id, groupId) => commit((c) => assignLayerGroup(c, id, groupId)),
    setPropertiesVisible: (visible) => commit((c) => setPropertiesVisible(c, visible)),
    setPropertiesOpacity: (opacity) => commit((c) => setPropertiesOpacity(c, opacity)),
  };
}

// ─────────────────────────────────────────────
// 永続化(localStorage / yadokari: 接頭辞の慣習に従う)
// ─────────────────────────────────────────────

export function loadLayerConfig(): LayerConfigState {
  try {
    const raw =
      typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
    if (!raw) return createDefaultLayerConfig();
    return normalizeLoadedConfig(JSON.parse(raw));
  } catch {
    return createDefaultLayerConfig();
  }
}

export function saveLayerConfig(config: LayerConfigState): void {
  try {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // ストレージ不可(プライベートモード等)でも動作を妨げない
  }
}

function normalizeLoadedConfig(parsed: unknown): LayerConfigState {
  if (!parsed || typeof parsed !== 'object') return createDefaultLayerConfig();
  const p = parsed as {
    v?: unknown;
    layers?: unknown;
    stack?: unknown;
    groups?: unknown;
    properties?: unknown;
  };

  // v2以外のペイロード(v1形式・破損含む)はデフォルト設定へフォールバック
  if (p.v !== 2 || !Array.isArray(p.stack)) {
    return createDefaultLayerConfig();
  }

  const groups: LayerGroup[] = (Array.isArray(p.groups) ? p.groups : [])
    .filter((g) => typeof g?.id === 'string' && typeof g?.name === 'string')
    .map((g) => ({
      id: g.id,
      name: g.name,
      visible: g.visible !== false,
      opacity: clamp01(g.opacity),
      collapsed: g.collapsed === true,
    }));
  const groupIds = new Set(groups.map((g) => g.id));

  const seen = new Set<string>();
  const stack: StackItem[] = [];
  for (const item of p.stack) {
    if (!item || typeof item !== 'object') continue;
    if (item.kind === 'layer') {
      const l = item as { id?: unknown; visible?: unknown; opacity?: unknown };
      if (typeof l.id !== 'string' || !catalogById.has(l.id) || seen.has(l.id)) continue;
      seen.add(l.id);
      stack.push({ kind: 'layer', id: l.id, visible: l.visible !== false, opacity: clamp01(l.opacity) });
    } else if (item.kind === 'group' && typeof item.groupId === 'string' && groupIds.has(item.groupId)) {
      const members: LayerRuntime[] = [];
      for (const m of Array.isArray(item.members) ? item.members : []) {
        if (
          m &&
          typeof m.id === 'string' &&
          catalogById.has(m.id) &&
          !seen.has(m.id)
        ) {
          seen.add(m.id);
          members.push({ id: m.id, visible: m.visible !== false, opacity: clamp01(m.opacity) });
        }
      }
      stack.push({ kind: 'group', groupId: item.groupId, members });
    }
  }
  // メタデータのみのグループは空ブロックを補完
  const blockIds = new Set(
    stack.filter((s) => s.kind === 'group').map((s) => (s as { groupId: string }).groupId),
  );
  for (const g of groups) {
    if (!blockIds.has(g.id)) stack.push({ kind: 'group', groupId: g.id, members: [] });
  }
  // 物件ピンランタイム(本フィールド導入前のconfigでは欠落するため補完)
  const pProps = (p.properties ?? null) as { visible?: unknown; opacity?: unknown } | null;
  const properties: LayerRuntime = {
    id: PROPERTIES_LAYER_ID,
    visible: pProps ? pProps.visible !== false : true,
    opacity: pProps ? clamp01(pProps.opacity) : 1,
  };
  return { v: 2, stack, groups, properties };
}
