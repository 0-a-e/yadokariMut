import React, { useCallback, useMemo, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MeasuringStrategy,
  closestCorners,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { dragStartZone } from '../../lib/layers/dnd.ts';
import { FaPlus, FaChevronDown } from 'react-icons/fa6';
import { Button } from '@/components/ui/button.tsx';
import { MultiCombobox } from '@/components/ui/combobox.tsx';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible.tsx';
import { cn } from '@/lib/utils.ts';
import { AdaptivePointerSensor } from '../../lib/layers/dnd.ts';
import type { LayerActions } from '../../lib/layers/state.ts';
import { flattenStack } from '../../lib/layers/state.ts';
import { catalogById, disabledEntries } from '../../lib/layers/catalog.ts';
import type { FeSettings } from '../../lib/feSettings.ts';
import {
  LAYER_TAGS,
  LAYER_TAG_LABELS,
  type LayerCatalogEntry,
  type LayerConfigState,
  type LayerGroup,
  type LayerRuntime,
  type LayerTag,
} from '../../lib/layers/types.ts';
import {
  DisabledLayerRow,
  DisabledLayerRowOverlay,
  EnabledLayerRow,
  EnabledLayerRowContent,
  EnabledLayerRowOverlay,
  GroupHeaderContent,
  markDragEnd,
} from './LayerRow.tsx';

/** DnDコンテナID(有効リスト / 無効リスト) */
const ENABLED_CONTAINER = 'layer-list-enabled';
const DISABLED_CONTAINER = 'layer-list-disabled';

/** グループブロックのドロップ領域ID接頭辞(id = `drop:<groupId>`) */
const GROUP_DROP_PREFIX = 'drop:';

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

/**
 * グループブロック(v2ネストスタック)。
 * - useSortable(id=groupId): グループ自体のトップレベル並べ替え(listenersはヘッダー)
 * - useDroppable(id=`drop:<groupId>`): レイヤの受け入れ領域(ブロック全体)
 * の二役。メンバーはネストした SortableContext で並べ替え。
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
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: group.id,
    data: { type: 'group' } satisfies DragData,
    animateLayoutChanges: () => false,
  });
  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `${GROUP_DROP_PREFIX}${group.id}`,
    data: { type: 'group', groupId: group.id } satisfies DragData,
  });
  const setRefs = useCallback(
    (node: HTMLElement | null) => {
      setNodeRef(node);
      setDropRef(node);
    },
    [setNodeRef, setDropRef],
  );

  return (
    <div
      ref={setRefs}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        'flex flex-col gap-1 rounded-lg transition-shadow',
        isDragging && 'opacity-40',
        isOver && 'ring-2 ring-primary/60',
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
              <p className="m-0 rounded-lg border border-dashed border-border/70 px-2 py-1.5 text-[10px] text-text-muted">
                ドラッグでレイヤを追加
              </p>
            ) : (
              members.map((m) => (
                <EnabledLayerRow
                  key={m.id}
                  layer={{ ...m, groupId: group.id }}
                  entry={catalogById.get(m.id)}
                  name={catalogById.get(m.id)?.name ?? m.id}
                  groups={groups}
                  groupColor={color}
                  layerActions={layerActions}
                  feSettings={feSettings}
                  onFeSettingsChange={onFeSettingsChange}
                />
              ))
            )}
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
  /** 折りたたみはUIローカル状態(LayerActionsに setter が無いため永続化しない) */
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const g of layerConfig.groups) if (g.collapsed) init[g.id] = true;
    return init;
  });

  // ドラッグ発火: ドラッガー(data-dnd-handle)は即時、行本体は長押し、操作系は発火なし。
  // センサはインスタンスごとに1つの発制約しか持てないため、既定を長押しにして
  // ドラッガー発火のみ bypassActivationConstraint で制約なし(即時)にする
  const sensors = useSensors(
    useSensor(AdaptivePointerSensor, {
      activationConstraint: { delay: 250, tolerance: 8 },
      bypassActivationConstraint: ({ event }) => dragStartZone(event) === 'handle',
    }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const { setNodeRef: enabledListRef } = useDroppable({ id: ENABLED_CONTAINER });
  const { setNodeRef: disabledListRef } = useDroppable({ id: DISABLED_CONTAINER });

  /** v2ネストスタックの平坦ビュー(グループはその位置に展開) */
  const enabledView = useMemo(() => flattenStack(layerConfig.stack), [layerConfig.stack]);
  const enabledIdSet = useMemo(() => new Set(enabledView.map((l) => l.id)), [enabledView]);

  /** トップレベル要素のid列(layerId or groupId。reorderStack の入力) */
  const topLevelIds = useMemo(
    () => layerConfig.stack.map((item) => (item.kind === 'layer' ? item.id : item.groupId)),
    [layerConfig.stack],
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

  /** id が属するリスト(有効/無効)を解決。表示中の無効リスト(フィルタ後)で判定 */
  const findList = useCallback(
    (id: string): 'enabled' | 'disabled' | undefined => {
      if (id === ENABLED_CONTAINER) return 'enabled';
      if (id === DISABLED_CONTAINER) return 'disabled';
      if (id.startsWith(GROUP_DROP_PREFIX)) return 'enabled';
      if (disabledIdSet.has(id)) return 'disabled';
      if (enabledIdSet.has(id)) return 'enabled';
      if (groupIds.has(id)) return 'enabled';
      return undefined;
    },
    [disabledIdSet, enabledIdSet, groupIds],
  );

  /**
   * カスタム衝突検出(dnd-kitネストDnDの落とし穴対策)。
   * - グループドラッグ: 他グループブロック(sortableノード)のみ候補(グループ間並べ替え)
   * - レイヤドラッグ: レイヤ行 + グループのドロップ領域(`drop:*`) + 両コンテナを候補
   *   (グループブロックの sortableノード自体は候補から除外し、drop領域と重複させない)
   */
  const collisionDetection: CollisionDetection = useCallback((args) => {
    const activeType = (args.active.data.current as DragData | undefined)?.type;
    const containers = args.droppableContainers.filter((container) => {
      const id = String(container.id);
      if (id === String(args.active.id)) return false;
      const data = container.data.current as DragData | undefined;
      if (activeType === 'group') {
        return data?.type === 'group' && !id.startsWith(GROUP_DROP_PREFIX);
      }
      if (id === ENABLED_CONTAINER || id === DISABLED_CONTAINER) return true;
      if (data?.type === 'layer') return true;
      return data?.type === 'group' && id.startsWith(GROUP_DROP_PREFIX);
    });
    if (containers.length === 0) return [];
    return closestCorners({ ...args, droppableContainers: containers });
  }, []);

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
   * 有効リスト内のホバー位置を反映(active は既に有効リスト内にある前提)。
   * - `drop:<gid>` へのホバー → moveToGroup(末尾追加)
   * - 他グループのメンバー行上 → moveToGroup(その位置へ挿入)
   * - グループ外のトップレベル行上 → removeFromGroup + reorderStack
   * - 同一所属内の行上 → reorderStack / reorderGroupMembers
   * baseレイヤは moveToGroup が不変を返すため黙って無効化される。
   */
  const applyEnabledHover = (activeId: string, overId: string) => {
    const activeGid = enabledView.find((l) => l.id === activeId)?.groupId;
    if (overId.startsWith(GROUP_DROP_PREFIX)) {
      const gid = overId.slice(GROUP_DROP_PREFIX.length);
      if (gid !== activeGid) layerActions.moveToGroup(activeId, gid);
      return;
    }
    const overGid = enabledView.find((l) => l.id === overId)?.groupId;
    if (overGid !== activeGid) {
      if (overGid != null) {
        const members = membersByGroup.get(overGid) ?? [];
        const index = members.findIndex((m) => m.id === overId);
        layerActions.moveToGroup(activeId, overGid, index >= 0 ? index : undefined);
      } else if (activeGid != null) {
        // グループ外へ払い出し(ブロック直後にトップレベルで置かれる。以降のhoverで位置確定)
        layerActions.removeFromGroup(activeId);
      }
      return;
    }
    if (activeGid != null) {
      const memberIds = (membersByGroup.get(activeGid) ?? []).map((m) => m.id);
      const oldIndex = memberIds.indexOf(activeId);
      const newIndex = memberIds.indexOf(overId);
      if (oldIndex >= 0 && newIndex >= 0 && oldIndex !== newIndex) {
        layerActions.reorderGroupMembers(activeGid, arrayMove(memberIds, oldIndex, newIndex));
      }
      return;
    }
    const oldIndex = topLevelIds.indexOf(activeId);
    const newIndex = topLevelIds.indexOf(overId);
    if (oldIndex >= 0 && newIndex >= 0 && oldIndex !== newIndex) {
      layerActions.reorderStack(arrayMove(topLevelIds, oldIndex, newIndex));
    }
  };

  /**
   * ドラッグ中のライブ反映(公式マルチコンテナパターン+ネスト拡張)。
   * - 有効→無効へ払い出し: removeLayer
   * - 無効→有効へ挿入: addLayer(先頭=最前面に仮置き。以降のhoverで位置が確定)
   * - グループドラッグ: reorderStack(グループ間の並べ替え)
   * - 有効リスト内: applyEnabledHover(グループ参加/脱离/並べ替え)
   */
  const handleDragOver = (event: DragOverEvent) => {
    const activeId = String(event.active.id);
    const overId = event.over ? String(event.over.id) : null;
    if (!overId || activeId === overId) return;

    const activeType = (event.active.data.current as DragData | undefined)?.type;
    if (activeType === 'group') {
      const oldIndex = topLevelIds.indexOf(activeId);
      const newIndex = topLevelIds.indexOf(overId);
      if (oldIndex >= 0 && newIndex >= 0 && oldIndex !== newIndex) {
        layerActions.reorderStack(arrayMove(topLevelIds, oldIndex, newIndex));
      }
      return;
    }

    const activeList = findList(activeId);
    const overList = findList(overId);
    if (!activeList || !overList) return;

    if (activeList === 'enabled' && overList === 'disabled') {
      layerActions.removeLayer(activeId);
      return;
    }
    if (activeList === 'disabled' && overList === 'enabled') {
      layerActions.addLayer(activeId);
      return;
    }
    if (activeList === 'enabled' && overList === 'enabled') {
      applyEnabledHover(activeId, overId);
    }
  };

  /**
   * ドロップ確定。ライブ反映済みなので有効リスト内の最終位置確定とクリーンアップのみ。
   * (dragOver直前の removeFromGroup など中間状態の残留を、ドロップ時のhover位置で確定する)
   */
  const handleDragEnd = (event: DragEndEvent) => {
    const activeId = String(event.active.id);
    const overId = event.over ? String(event.over.id) : null;
    setActiveDrag(null);
    if (!overId || activeId === overId) return;

    const activeType = (event.active.data.current as DragData | undefined)?.type;
    if (activeType === 'group') return; // dragOverで確定済み

    const activeList = findList(activeId);
    const overList = findList(overId);
    if (activeList === 'enabled' && overList === 'enabled') {
      applyEnabledHover(activeId, overId);
    }
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
        measuring={{ droppable: { strategy: MeasuringStrategy.WhileDragging } }}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={(event) => {
          markDragEnd();
          handleDragEnd(event);
        }}
        onDragCancel={() => {
          markDragEnd();
          setActiveDrag(null);
        }}
      >
        <div className="app-scrollbar flex min-h-0 grow flex-col gap-4 overflow-y-auto p-4">
          {/* ── 有効レイヤ(上位=前面。グループはネストブロック表示) ── */}
          <section className="flex flex-col gap-1.5">
            <div className="flex justify-between text-xs font-semibold uppercase tracking-[1px] text-text-muted">
              <span>有効レイヤ</span>
              <span className="font-semibold normal-case tracking-normal text-accent">
                {enabledView.length}枚
              </span>
            </div>
            <SortableContext items={topLevelIds} strategy={verticalListSortingStrategy}>
              <div
                ref={enabledListRef}
                className={cn(
                  'flex min-h-14 flex-col gap-1 rounded-lg transition-colors',
                  activeDrag != null && activeDrag.from === 'disabled' && 'bg-primary/5',
                )}
              >
                {layerConfig.stack.length === 0 ? (
                  <p className="m-0 rounded-lg border border-dashed border-border px-3 py-3 text-center text-[11px] text-text-muted">
                    有効なレイヤはありません。
                    <br />
                    下の無効レイヤから追加してください
                  </p>
                ) : (
                  layerConfig.stack.map((item) => {
                    if (item.kind === 'layer') {
                      const entry = catalogById.get(item.id);
                      return (
                        <EnabledLayerRow
                          key={item.id}
                          layer={item}
                          entry={entry}
                          name={entry?.name ?? item.id}
                          groups={layerConfig.groups}
                          layerActions={layerActions}
                          feSettings={feSettings}
                          onFeSettingsChange={onFeSettingsChange}
                        />
                      );
                    }
                    const group = groupsById.get(item.groupId);
                    if (!group) return null;
                    return (
                      <GroupBlock
                        key={item.groupId}
                        group={group}
                        members={item.members}
                        color={groupColor(group.id)}
                        collapsed={collapsedGroups[group.id] ?? false}
                        onToggleCollapsed={() => toggleCollapsed(group.id)}
                        layerActions={layerActions}
                        groups={layerConfig.groups}
                        feSettings={feSettings}
                        onFeSettingsChange={onFeSettingsChange}
                      />
                    );
                  })
                )}
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
              (順序変更・グループへの移動・無効リストへの移動)
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
                ref={disabledListRef}
                className={cn(
                  'flex min-h-14 flex-col gap-1 rounded-lg transition-colors',
                  activeDrag != null && activeDrag.from === 'enabled' && 'bg-primary/5',
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
