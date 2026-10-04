import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  useSensor,
  useSensors,
  type Collision,
  type CollisionDetection,
  type DragEndEvent,
  type DragMoveEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { dragStartZone } from '../../lib/layers/dnd.ts';
import { FaPlus, FaChevronDown } from 'react-icons/fa6';
import { Button } from '@/components/ui/button.tsx';
import { MultiCombobox } from '@/components/ui/combobox.tsx';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible.tsx';
import { cn } from '@/lib/utils.ts';
import { AdaptivePointerSensor } from '../../lib/layers/dnd.ts';
import type { DropPosition, LayerActions } from '../../lib/layers/state.ts';
import { flattenStack } from '../../lib/layers/state.ts';
import { catalogById, disabledEntries } from '../../lib/layers/catalog.ts';
import type { FeSettings } from '../../lib/feSettings.ts';
import type { BaseLayerId } from '../../lib/layers/types.ts';
import {
  LAYER_TAGS,
  LAYER_TAG_LABELS,
  PROPERTIES_LAYER_ID,
  type LayerCatalogEntry,
  type LayerConfigState,
  type LayerGroup,
  type LayerRuntime,
  type LayerTag,
} from '../../lib/layers/types.ts';
import {
  BaseLayerRow,
  DisabledLayerRow,
  DisabledLayerRowOverlay,
  EnabledLayerRow,
  EnabledLayerRowContent,
  EnabledLayerRowOverlay,
  GroupHeaderContent,
  PropertiesLayerRow,
  markDragEnd,
} from './LayerRow.tsx';

/** DnDコンテナID(有効リスト / 無効リスト) */
const ENABLED_CONTAINER = 'layer-list-enabled';
const DISABLED_CONTAINER = 'layer-list-disabled';

/** ドロップ可能要素の data 型(カスタム衝突検出のフィルタに使用) */
type DragData = { type: 'layer'; groupId?: string } | { type: 'group'; groupId?: string };

/** グループ縦バーの色パレット(グループ配列の順で巡回) */
const GROUP_COLORS = [
  '#ff6b6b',
  '#ffb300',
  '#00e676',
  '#4dabf7',
  '#b197fc',
  '#f783ac',
  '#22d3ee',
  '#a3e635',
] as const;

/** タグ→LAYER_TAGS定義順のインデックス(未定義タグは最後尾) */
const TAG_ORDER: ReadonlyMap<LayerTag, number> = new Map(
  LAYER_TAGS.map((t, i) => [t.id, i] as const),
);
const tagOrderOf = (tag: LayerTag | undefined): number =>
  tag != null ? (TAG_ORDER.get(tag) ?? LAYER_TAGS.length) : LAYER_TAGS.length;

interface LayerPanelFeSettingsProps {
  feSettings: FeSettings;
  onFeSettingsChange: (update: FeSettings) => Promise<FeSettings | null>;
}

interface LayerPanelProps extends LayerPanelFeSettingsProps {
  layerConfig: LayerConfigState;
  layerActions: LayerActions;
}

/** 挿入位置インジケータ(ドロップ予定位置を示す横線) */
const InsertIndicator: React.FC = () => (
  <span aria-hidden className="block h-0.5 shrink-0 rounded-full bg-accent" />
);

/**
 * グループブロック(v2ネストスタック)。
 * - useSortable(id=groupId): グループ自体のトップレベル並べ替え(listenersはヘッダー)
 * - useDroppable(id=`drop:<groupId>`): レイヤの受け入れ領域(ブロック全体)
 * の二役。メンバーはネストした SortableContext で並べ替え。
 * 挿入はドロップ時一括確定のため、メンバーの位置はドラッグ中も動かさず、
 * dropIndex 位置にインジケータ線を表示する。
 */
const GroupBlock: React.FC<{
  group: LayerGroup;
  members: LayerRuntime[];
  color: string;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  layerActions: LayerActions;
  groups: LayerGroup[];
  feSettings: FeSettings;
  onFeSettingsChange: (update: FeSettings) => Promise<FeSettings | null>;
  /** グループメンバー列への挿入インジケータ位置(null=非表示) */
  dropIndex?: number | null;
  /** ドロップ先がこのグループ領域(ヘッダー/余白)のときの強調 */
  isGroupTarget?: boolean;
}> = ({
  group,
  members,
  color,
  collapsed,
  onToggleCollapsed,
  layerActions,
  groups,
  feSettings,
  onFeSettingsChange,
  dropIndex = null,
  isGroupTarget = false,
}) => {
  const { attributes, listeners, setNodeRef, isDragging } = useSortable({
    id: group.id,
    data: { type: 'group' } satisfies DragData,
  });

  return (
    <div
      ref={setNodeRef}
      data-layer-row={group.id}
      className={cn(
        'flex flex-col gap-1 rounded-lg transition-shadow',
        isDragging && 'opacity-40',
        isGroupTarget && 'ring-2 ring-primary/60',
      )}
    >
      <GroupHeaderContent
        group={group}
        memberCount={members.length}
        color={color}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        layerActions={layerActions}
        dragBindings={{ attributes, listeners }}
      />
      {!collapsed && (
        <SortableContext items={members.map((m) => m.id)} strategy={verticalListSortingStrategy}>
          <div className="flex min-h-8 flex-col gap-1 pl-3">
            {members.length === 0 ? (
              <div className="m-0 flex flex-col gap-0.5 rounded-lg border border-dashed border-border/70 px-2 py-1.5">
                {dropIndex === 0 && <InsertIndicator />}
                <p className="m-0 text-[10px] text-text-muted">ドラッグでレイヤを追加</p>
              </div>
            ) : (
              members.map((m, j) => (
                <React.Fragment key={m.id}>
                  {dropIndex === j && <InsertIndicator />}
                  <EnabledLayerRow
                    layer={{ ...m, groupId: group.id }}
                    entry={catalogById.get(m.id)}
                    name={catalogById.get(m.id)?.name ?? m.id}
                    groups={groups}
                    groupColor={color}
                    layerActions={layerActions}
                    feSettings={feSettings}
                    onFeSettingsChange={onFeSettingsChange}
                  />
                </React.Fragment>
              ))
            )}
            {members.length > 0 && dropIndex === members.length && <InsertIndicator />}
          </div>
        </SortableContext>
      )}
    </div>
  );
};

/** ドラッグ中のグループブロックを DragOverlay に描くための静的コピー */
const GroupBlockOverlay: React.FC<{
  group: LayerGroup;
  members: LayerRuntime[];
  color: string;
  width?: number;
  layerActions: LayerActions;
  groups: LayerGroup[];
  feSettings: FeSettings;
  onFeSettingsChange: (update: FeSettings) => Promise<FeSettings | null>;
}> = ({ group, members, color, width, layerActions, groups, feSettings, onFeSettingsChange }) => (
  <div
    style={width != null ? { width } : undefined}
    className="pointer-events-none flex flex-col gap-1 rounded-lg ring-2 ring-primary/70 shadow-xl"
  >
    <GroupHeaderContent group={group} memberCount={members.length} color={color} collapsed={false} />
    {members.map((m) => {
      const entry = catalogById.get(m.id);
      return (
        <EnabledLayerRowContent
          key={m.id}
          layer={{ ...m, groupId: group.id }}
          entry={entry}
          name={entry?.name ?? m.id}
          groups={groups}
          groupColor={color}
          layerActions={layerActions}
          feSettings={feSettings}
          onFeSettingsChange={onFeSettingsChange}
        />
      );
    })}
  </div>
);

/** ドラッグ中アイテムの情報(DragOverlay描画用) */
interface ActiveDrag {
  id: string;
  type: DragData['type'];
  from: 'enabled' | 'disabled';
  width?: number;
}

/**
 * DnD確定時のドロップ先。ドラッグ中はライブ反映せず、この解決結果を
 * インジケータ表示に使う。ドロップ時(dragEnd)に一括適用する。
 */
type DropTarget =
  | { kind: 'top'; index: number }
  | { kind: 'group'; groupId: string; index: number }
  | { kind: 'disabled' }
  | { kind: 'base-swap' };

/** DropTarget → placeLayer の位置指定(top/groupのみ) */
const toPlacePosition = (target: DropTarget): DropPosition | null =>
  target.kind === 'top'
    ? { kind: 'top', index: target.index }
    : target.kind === 'group'
      ? { kind: 'group', groupId: target.groupId, index: target.index }
      : null;

/**
 * 地図レイヤパネル(GIMP方式: 有効リストの上位=前面)。
 * v2ネストスタックモデルの描画とDnD:
 * - トップレベル: SortableContext(layerId + groupId) → reorderStack
 * - グループ内: ネストした SortableContext(members) → reorderGroupMembers / moveToGroup / removeFromGroup
 * - 無効リスト⇔有効(グループ含む)の相互DnD(addLayer / removeLayer)
 */
export const LayerPanel: React.FC<LayerPanelProps> = ({
  layerConfig,
  layerActions,
  feSettings,
  onFeSettingsChange,
}) => {
  const [selectedTags, setSelectedTags] = useState<LayerTag[]>([]);
  const [query, setQuery] = useState('');
  /** 無効レイヤのタググループ折りたたみ(key=タグid or 'other')。既定は折りたたみ */
  const [openTagGroups, setOpenTagGroups] = useState<Record<string, boolean>>({});
  const [activeDrag, setActiveDrag] = useState<ActiveDrag | null>(null);
  /** ドロップ予定先(dragMove毎に解決。ドラッグ中のライブ反映は行わない) */
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  /** 折りたたみはUIローカル状態(LayerActionsに setter が無いため永続化しない) */
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const g of layerConfig.groups) if (g.collapsed) init[g.id] = true;
    return init;
  });

  // ドラッグ発火: ドラッガー(data-dnd-handle)は即時、行本体は長押し、操作系は発火なし。
  // センサはインスタンスごとに1つの発制約しか持てないため、既定を長押しにして
  // ドラッガー発火のみ bypassActivationConstraint で制約なし(即時)にする。
  // tolerance を緩め(20px)にし、素早いドラッグ意図でも発火がキャンセルされにくくする
  const sensors = useSensors(
    useSensor(AdaptivePointerSensor, {
      activationConstraint: { delay: 250, tolerance: 20 },
      bypassActivationConstraint: ({ event }) => dragStartZone(event) === 'handle',
    }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const panelRootRef = useRef<HTMLDivElement>(null);
  const enabledListElRef = useRef<HTMLDivElement>(null);
  const disabledListElRef = useRef<HTMLDivElement>(null);

  /** v2ネストスタックの平坦ビュー(グループはその位置に展開) */
  const enabledView = useMemo(() => flattenStack(layerConfig.stack), [layerConfig.stack]);
  const enabledIdSet = useMemo(() => new Set(enabledView.map((l) => l.id)), [enabledView]);

  /** トップレベル要素のid列(layerId or groupId。reorderStack の入力) */
  const topLevelIds = useMemo(
    () => layerConfig.stack.map((item) => (item.kind === 'layer' ? item.id : item.groupId)),
    [layerConfig.stack],
  );

  /** ベース行はドラッグ不可のため SortableContext の items から除外 */
  const sortableTopLevelIds = useMemo(
    () => topLevelIds.filter((id) => catalogById.get(id)?.role !== 'base'),
    [topLevelIds],
  );

  /** ドロップ先がベース行の位置より後ろ(top末尾)のときのインジケータ位置 */
  const topIndicatorIndex = dropTarget?.kind === 'top' ? dropTarget.index : null;
  const groupDropIndex = useCallback(
    (gid: string): number | null =>
      dropTarget?.kind === 'group' && dropTarget.groupId === gid ? dropTarget.index : null,
    [dropTarget],
  );

  const membersByGroup = useMemo(() => {
    const map = new Map<string, LayerRuntime[]>();
    for (const item of layerConfig.stack) {
      if (item.kind === 'group') map.set(item.groupId, item.members);
    }
    return map;
  }, [layerConfig.stack]);

  const groupIds = useMemo(() => new Set(layerConfig.groups.map((g) => g.id)), [layerConfig.groups]);

  /** 無効レイヤ(タグ定義順→名前順)を検索条件(名前 or タグラベル)で絞り込んだリスト */
  const filteredDisabled = useMemo(() => {
    const all = disabledEntries(enabledIdSet);
    const q = query.trim().toLowerCase();
    if (selectedTags.length === 0 && !q) return all;
    return all.filter((entry) => {
      const hasAllTags = selectedTags.every((tag) => entry.tags.includes(tag));
      if (!hasAllTags) return false;
      if (!q) return true;
      return (
        entry.name.toLowerCase().includes(q) ||
        entry.tags.some((tag) => LAYER_TAG_LABELS[tag].toLowerCase().includes(q))
      );
    });
  }, [enabledIdSet, selectedTags, query]);

  /**
   * 絞り込み後の無効レイヤを先頭タグごとにグループ化(LAYER_TAGS定義順。未定義タグは最後尾)。
   * disabledEntries がタグ定義順にソート済みのため、同タグのエントリは連続する
   */
  const disabledGroups = useMemo(() => {
    const byTag = new Map<LayerTag | undefined, LayerCatalogEntry[]>();
    for (const entry of filteredDisabled) {
      const list = byTag.get(entry.tags[0]);
      if (list) list.push(entry);
      else byTag.set(entry.tags[0], [entry]);
    }
    return [...byTag.entries()].sort((a, b) => tagOrderOf(a[0]) - tagOrderOf(b[0]));
  }, [filteredDisabled]);

  /** 検索中(検索語入力 or タグ選択)は全グループを自動展開 */
  const searchActive = query.trim() !== '' || selectedTags.length > 0;

  const disabledIds = useMemo(() => filteredDisabled.map((e) => e.id), [filteredDisabled]);
  const disabledIdSet = useMemo(() => new Set(disabledIds), [disabledIds]);

  const tagItems = useMemo(() => LAYER_TAGS.map((t) => ({ value: t.id, label: t.label })), []);

  const groupIndexById = useMemo(() => {
    const map = new Map<string, number>();
    layerConfig.groups.forEach((g, i) => map.set(g.id, i));
    return map;
  }, [layerConfig.groups]);
  const groupColor = (groupId: string) =>
    GROUP_COLORS[(groupIndexById.get(groupId) ?? 0) % GROUP_COLORS.length];

  const groupsById = useMemo(
    () => new Map(layerConfig.groups.map((g) => [g.id, g])),
    [layerConfig.groups],
  );

  const toggleCollapsed = useCallback((groupId: string) => {
    setCollapsedGroups((prev) => ({ ...prev, [groupId]: !prev[groupId] }));
  }, []);

  /**
   * カスタム衝突検出。dnd-kit の droppable レジストリ(useDroppable 単独のコンテナが
   * 測定対象から欠落する問題がある)に頼らず、パネル内の実DOM rect とポインタ座標で
   * 直接解決する。候補の優先順: ポインタ直下の行 > リストコンテナ。
   * 行同士は重ならないため結果は一意に定まり、衝突の不定性を排する。
   */
  const collisionDetection: CollisionDetection = useCallback((args) => {
    const root = panelRootRef.current;
    const enabledList = enabledListElRef.current;
    const disabledList = disabledListElRef.current;
    const pointer = args.pointerCoordinates;
    if (!root || !pointer) return [];

    const contains = (r: DOMRect, p: { x: number; y: number }) =>
      p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom;

    // ポインタ直下の行(useSortable の全行に data-layer-row を付与)
    const hits: Collision[] = [];
    const rows = root.querySelectorAll<HTMLElement>('[data-layer-row]');
    for (const el of rows) {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;
      if (!contains(rect, pointer)) continue;
      hits.push({ id: el.dataset.layerRow!, data: { rect } });
    }
    if (hits.length > 0) return hits;

    // 行の隙間/余白は所属リストコンテナで判定
    if (enabledList && contains(enabledList.getBoundingClientRect(), pointer)) {
      return [{ id: ENABLED_CONTAINER }];
    }
    if (disabledList && contains(disabledList.getBoundingClientRect(), pointer)) {
      return [{ id: DISABLED_CONTAINER }];
    }
    // パネル外(ドロップ意図なし)は候補なし → over=null → 何も起きない
    return [];
  }, []);

  /** ドラッグ開始直後のクリック抑制とオーバーレイ用の情報記録 */
  const handleDragStart = (event: DragStartEvent) => {
    const id = String(event.active.id);
    const data = event.active.data.current as DragData | undefined;
    const width = event.active.rect.current.initial?.width;
    setActiveDrag({
      id,
      type: data?.type ?? 'layer',
      from: data?.type === 'group' || enabledIdSet.has(id) ? 'enabled' : 'disabled',
      width,
    });
  };

  /**
   * ドロップ先の解決(dragMove毎に呼ぶ。ドラッグ中のレイヤ構成には触れない)。
   * collisions は collisionDetection の優先順リスト(行 > drop領域 > コンテナ)。
   * 行へのホバーはポインタYと行中心の前後で挿入位置(直前/直後)を確定する。
   * ベースドラッグは有効リスト側で差し替え、無効リスト側では受理しない。
   */
  const resolveDropTarget = useCallback(
    (event: DragMoveEvent | DragEndEvent): DropTarget | null => {
      const collisions = event.collisions ?? [];
      if (collisions.length === 0) return null;
      const activeId = String(event.active.id);
      const activeType = (event.active.data.current as DragData | undefined)?.type;
      const activeIsBase = catalogById.get(activeId)?.role === 'base';

      // ポインタの現在Y(押下位置+移動量)。行の上下判定に使用
      const activator = event.activatorEvent as PointerEvent | null;
      const pointerY =
        activator && typeof activator.clientY === 'number'
          ? activator.clientY + (event.delta?.y ?? 0)
          : null;

      const baseStackIndex = layerConfig.stack.findIndex(
        (item) => item.kind === 'layer' && catalogById.get(item.id)?.role === 'base',
      );

      for (const collision of collisions) {
        const id = String(collision.id);
        // collisionDetection が行の実DOM rect を data.rect に入れて渡す
        const rowRect = (collision.data as { rect?: DOMRect } | undefined)?.rect;
        const isAfter =
          rowRect && pointerY != null ? pointerY > rowRect.top + rowRect.height / 2 : false;

        if (activeIsBase) {
          // ベースドラッグ: 有効リスト側なら差し替え。無効リスト側は受理しない(base不在を防ぐ)
          if (id === DISABLED_CONTAINER || disabledIdSet.has(id)) return null;
          return { kind: 'base-swap' };
        }

        // 物件ピン行(最前面固定の特殊行): 直後(スタック先頭)のみ指定可。
        // 物件行の上半分/下半分は区別しない(最前面固定のため上へは挿入できない)
        if (id === PROPERTIES_LAYER_ID) {
          return { kind: 'top', index: 0 };
        }

        if (id === DISABLED_CONTAINER || disabledIdSet.has(id)) return { kind: 'disabled' };
        if (id === ENABLED_CONTAINER) {
          // 空き領域は末尾(ベース行の直前)へ
          return {
            kind: 'top',
            index: baseStackIndex >= 0 ? baseStackIndex : layerConfig.stack.length,
          };
        }

        // グループブロック自体の上
        if (groupIds.has(id)) {
          if (activeType === 'group') {
            // グループドラッグ: トップレベルの挿入位置(直前/直後)
            const overTopIndex = topLevelIds.indexOf(id);
            if (overTopIndex >= 0) {
              return { kind: 'top', index: overTopIndex + (isAfter ? 1 : 0) };
            }
          } else {
            // レイヤドラッグ: そのグループへの末尾追加
            return { kind: 'group', groupId: id, index: (membersByGroup.get(id) ?? []).length };
          }
          continue;
        }

        // 有効行の上: 行の上下で挿入位置(直前/直後)を決める
        const overGid = enabledView.find((l) => l.id === id)?.groupId;
        if (overGid != null) {
          const members = membersByGroup.get(overGid) ?? [];
          const memberIndex = members.findIndex((m) => m.id === id);
          if (memberIndex >= 0) {
            return { kind: 'group', groupId: overGid, index: memberIndex + (isAfter ? 1 : 0) };
          }
        }
        const topIndex = layerConfig.stack.findIndex((s) => s.kind === 'layer' && s.id === id);
        if (topIndex >= 0) {
          return { kind: 'top', index: topIndex + (isAfter ? 1 : 0) };
        }
      }
      return null;
    },
    [disabledIdSet, enabledView, membersByGroup, layerConfig.stack, topLevelIds, groupIds],
  );

  /** トップレベル要素(レイヤ/グループ)を移動前座標系の挿入位置へ並べ替えた順列 */
  const moveTopLevelTo = useCallback((ids: string[], id: string, toIndex: number): string[] => {
    const from = ids.indexOf(id);
    if (from < 0) return ids;
    const rest = ids.filter((x) => x !== id);
    const insertAt = Math.max(0, Math.min(from < toIndex ? toIndex - 1 : toIndex, rest.length));
    return [...rest.slice(0, insertAt), id, ...rest.slice(insertAt)];
  }, []);

  /**
   * ドロップ確定。ドラッグ中に溜めた解決結果を一括適用する。
   * ライブ反映がないため、ここがレイヤ構成を変更する唯一の箇所。
   */
  const applyDrop = useCallback(
    (event: DragEndEvent, target: DropTarget | null) => {
      if (!target) return;
      const activeId = String(event.active.id);
      const activeType = (event.active.data.current as DragData | undefined)?.type;

      if (activeType === 'group') {
        if (target.kind === 'top') {
          layerActions.reorderStack(moveTopLevelTo(topLevelIds, activeId, target.index));
        }
        return;
      }
      switch (target.kind) {
        case 'top':
        case 'group': {
          const position = toPlacePosition(target);
          if (position) layerActions.placeLayer(activeId, position);
          break;
        }
        case 'disabled':
          if (enabledIdSet.has(activeId)) layerActions.removeLayer(activeId);
          break;
        case 'base-swap':
          layerActions.selectBase(activeId as BaseLayerId);
          break;
      }
    },
    [enabledIdSet, layerActions, moveTopLevelTo, topLevelIds],
  );

  /** ドラッグ中のライブ反映(dragMove)。レイヤ構成は触れず、ドロップ先の解決のみ行う */
  const handleDragMove = (event: DragMoveEvent) => {
    setDropTarget(resolveDropTarget(event));
  };

  /** DragOverlay の描画内容(ドラッグ中の行/グループの静的コピー) */
  const renderOverlay = () => {
    if (!activeDrag) return null;
    if (activeDrag.type === 'group') {
      const group = groupsById.get(activeDrag.id);
      const item = layerConfig.stack.find(
        (s) => s.kind === 'group' && s.groupId === activeDrag.id,
      );
      if (!group || !item || item.kind !== 'group') return null;
      return (
        <GroupBlockOverlay
          group={group}
          members={item.members}
          color={groupColor(group.id)}
          width={activeDrag.width}
          layerActions={layerActions}
          groups={layerConfig.groups}
          feSettings={feSettings}
          onFeSettingsChange={onFeSettingsChange}
        />
      );
    }
    if (activeDrag.from === 'enabled') {
      const layer = enabledView.find((l) => l.id === activeDrag.id);
      const entry = layer ? catalogById.get(layer.id) : undefined;
      if (!layer) return null;
      return (
        <EnabledLayerRowOverlay
          layer={layer}
          entry={entry}
          name={entry?.name ?? layer.id}
          groups={layerConfig.groups}
          groupColor={layer.groupId ? groupColor(layer.groupId) : undefined}
          layerActions={layerActions}
          feSettings={feSettings}
          onFeSettingsChange={onFeSettingsChange}
          width={activeDrag.width}
        />
      );
    }
    const entry =
      filteredDisabled.find((e) => e.id === activeDrag.id) ?? catalogById.get(activeDrag.id);
    if (!entry) return null;
    return <DisabledLayerRowOverlay entry={entry} width={activeDrag.width} />;
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <DndContext
        sensors={sensors}
        collisionDetection={collisionDetection}
        onDragStart={handleDragStart}
        onDragMove={handleDragMove}
        onDragEnd={(event) => {
          markDragEnd();
          applyDrop(event, resolveDropTarget(event));
          setActiveDrag(null);
          setDropTarget(null);
        }}
        onDragCancel={() => {
          markDragEnd();
          setActiveDrag(null);
          setDropTarget(null);
        }}
      >
        <div
          ref={panelRootRef}
          className="app-scrollbar flex min-h-0 grow flex-col gap-4 overflow-y-auto p-4"
        >
          {/* ── 有効レイヤ(上位=前面。グループはネストブロック表示) ── */}
          <section className="flex flex-col gap-1.5">
            <div className="flex justify-between text-xs font-semibold uppercase tracking-[1px] text-text-muted">
              <span>有効レイヤ</span>
              <span className="font-semibold normal-case tracking-normal text-accent">
                {enabledView.length}枚
              </span>
            </div>
            <SortableContext items={sortableTopLevelIds} strategy={verticalListSortingStrategy}>
              <div
                ref={enabledListElRef}
                className={cn(
                  'flex min-h-14 flex-col gap-1 rounded-lg transition-colors',
                  activeDrag != null && activeDrag.from === 'disabled' && 'bg-primary/5',
                )}
              >
                {/* 物件ピン行(最前面固定の特殊行)。スタック外で常駐のためドラッグ不可。
                    data-layer-row は collisionDetection の over 判定に必要
                    (resolveDropTarget 側で index 0 への挿入に解決される) */}
                <div data-layer-row={PROPERTIES_LAYER_ID}>
                  <PropertiesLayerRow layer={layerConfig.properties} layerActions={layerActions} />
                </div>
                {layerConfig.stack.length === 0 ? (
                  <p className="m-0 rounded-lg border border-dashed border-border px-3 py-3 text-center text-[11px] text-text-muted">
                    有効なレイヤはありません。
                    <br />
                    下の無効レイヤから追加してください
                  </p>
                ) : (
                  layerConfig.stack.map((item, i) => {
                    const itemId = item.kind === 'layer' ? item.id : item.groupId;
                    const entry = item.kind === 'layer' ? catalogById.get(item.id) : undefined;
                    let content: React.ReactNode = null;
                    if (item.kind === 'layer') {
                      content =
                        entry?.role === 'base' ? (
                          <BaseLayerRow
                            layer={item}
                            entry={entry}
                            name={entry?.name ?? item.id}
                            groups={[]}
                            layerActions={layerActions}
                            feSettings={feSettings}
                            onFeSettingsChange={onFeSettingsChange}
                            isSwapTarget={dropTarget?.kind === 'base-swap'}
                          />
                        ) : (
                          <EnabledLayerRow
                            layer={item}
                            entry={entry}
                            name={entry?.name ?? item.id}
                            groups={layerConfig.groups}
                            layerActions={layerActions}
                            feSettings={feSettings}
                            onFeSettingsChange={onFeSettingsChange}
                          />
                        );
                    } else {
                      const group = groupsById.get(item.groupId);
                      content = group ? (
                        <GroupBlock
                          group={group}
                          members={item.members}
                          color={groupColor(group.id)}
                          collapsed={collapsedGroups[group.id] ?? false}
                          onToggleCollapsed={() => toggleCollapsed(group.id)}
                          layerActions={layerActions}
                          groups={layerConfig.groups}
                          feSettings={feSettings}
                          onFeSettingsChange={onFeSettingsChange}
                          dropIndex={groupDropIndex(item.groupId)}
                          isGroupTarget={
                            dropTarget?.kind === 'group' && dropTarget.groupId === item.groupId
                          }
                        />
                      ) : null;
                    }
                    return (
                      <React.Fragment key={itemId}>
                        {topIndicatorIndex === i && <InsertIndicator />}
                        {content}
                      </React.Fragment>
                    );
                  })
                )}
                {topIndicatorIndex === layerConfig.stack.length && <InsertIndicator />}
              </div>
            </SortableContext>
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs font-semibold text-text-muted hover:text-text"
              onClick={() => layerActions.addGroup('')}
            >
              <FaPlus data-icon="inline-start" />
              グループ作成
            </Button>
            <p className="m-0 text-[10px] text-text-muted/80">
              上=前面。ハンドルは即時ドラッグ、行の他の部分は長押しでドラッグ
              (順序変更・グループへの移動・無効リストへの移動)。
              物件ピンは最前面固定、基本地図は最下層固定
            </p>
          </section>

          {/* ── 無効レイヤ(検索) ── */}
          <section className="flex flex-col gap-1.5">
            <div className="flex justify-between text-xs font-semibold uppercase tracking-[1px] text-text-muted">
              <span>無効レイヤ</span>
              <span className="font-semibold normal-case tracking-normal text-accent">
                {filteredDisabled.length}件
              </span>
            </div>
            <MultiCombobox
              ariaLabel="タグ検索"
              items={tagItems}
              value={selectedTags}
              onValueChange={(values) => setSelectedTags(values as LayerTag[])}
              onInputValueChange={setQuery}
              placeholder="タグまたはレイヤ名で検索…"
            />
            <SortableContext items={disabledIds} strategy={verticalListSortingStrategy}>
              <div
                ref={disabledListElRef}
                className={cn(
                  'flex min-h-14 flex-col gap-1 rounded-lg transition-colors',
                  dropTarget?.kind === 'disabled' && 'bg-primary/5',
                )}
              >
                {filteredDisabled.length === 0 ? (
                  <p className="m-0 rounded-lg border border-dashed border-border px-3 py-3 text-center text-[11px] text-text-muted">
                    {selectedTags.length === 0 && !query.trim()
                      ? 'すべてのレイヤが有効です'
                      : '該当するレイヤはありません'}
                  </p>
                ) : (
                  disabledGroups.map(([tag, entries]) => {
                    const key = tag ?? 'other';
                    const open = searchActive || openTagGroups[key] === true;
                    return (
                      <Collapsible
                        key={key}
                        open={open}
                        onOpenChange={(next) =>
                          setOpenTagGroups((prev) => ({ ...prev, [key]: next }))
                        }
                      >
                        <CollapsibleTrigger className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs font-semibold text-text-muted hover:text-text">
                          <span>
                            {tag != null ? LAYER_TAG_LABELS[tag] : 'その他'} ({entries.length})
                          </span>
                          <FaChevronDown
                            className={cn('text-[10px] transition-transform', open && 'rotate-180')}
                          />
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <div className="flex flex-col gap-1 py-1 pl-1">
                            {entries.map((entry) => (
                              <DisabledLayerRow
                                key={entry.id}
                                entry={entry}
                                layerActions={layerActions}
                              />
                            ))}
                          </div>
                        </CollapsibleContent>
                      </Collapsible>
                    );
                  })
                )}
              </div>
            </SortableContext>
          </section>
        </div>
        <DragOverlay>{renderOverlay()}</DragOverlay>
      </DndContext>
    </div>
  );
};
