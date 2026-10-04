import React, { useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import {
  FaArrowRightArrowLeft,
  FaCheck,
  FaChevronDown,
  FaCircleXmark,
  FaEye,
  FaEyeSlash,
  FaGear,
  FaGripVertical,
  FaPlus,
  FaTrashCan,
} from 'react-icons/fa6';
import { Button } from '@/components/ui/button.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import { Slider } from '@/components/ui/slider.tsx';
import { Menu, MenuTrigger, MenuContent, MenuItem } from '@/components/ui/menu.tsx';
import { cn } from '@/lib/utils.ts';
import { DND_HANDLE_ATTR } from '../../lib/layers/dnd.ts';
import type { LayerActions } from '../../lib/layers/state.ts';
import type { FeSettings } from '../../lib/feSettings.ts';
import { baseEntries } from '../../lib/layers/catalog.ts';
import type { BaseLayerId } from '../../lib/layers/types.ts';
import {
  LAYER_TAG_LABELS,
  type LayerCatalogEntry,
  type LayerGroup,
  type LayerRuntime,
} from '../../lib/layers/types.ts';
import { LayerLegendPopover } from './LayerLegendPopover.tsx';
import { LayerSettingsDialog } from './LayerSettingsDialog.tsx';

/** useSortable のバインディング(attributes/listeners)の型 */
type SortableBindings = Pick<ReturnType<typeof useSortable>, 'attributes' | 'listeners'>;

// ── ドラッグ開始直後のクリック抑制(長押しドラッグ終了で click が行本体に
//    飛び、無効行のクリック有効化が誤発火するのを防ぐ) ──
let lastDragEndAt = 0;

/** DnD終了直後であることを記録。LayerPanel の onDragEnd/onDragCancel から呼ぶ */
export function markDragEnd(): void {
  lastDragEndAt = Date.now();
}

function suppressClickAfterDrag(): boolean {
  return Date.now() - lastDragEndAt < 150;
}

/** ドラッグハンドル(視覚+即時発火ゾーンの目印)。リスナーは行全体に付く */
function DragHandle({ label }: { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...{ [DND_HANDLE_ATTR]: "" }}
      className={cn(
        'flex size-4 shrink-0 cursor-grab touch-none select-none items-center justify-center rounded',
        'text-text-muted/70 transition-colors hover:text-text active:cursor-grabbing',
      )}
      onClick={(e) => e.stopPropagation()}
    >
      <FaGripVertical className="size-2.5" />
    </button>
  );
}

/** 有効/無効レイヤ行の共通props(設定モーダル伝達を含む) */
interface LayerRowFeSettingsProps {
  feSettings: FeSettings;
  onFeSettingsChange: (update: FeSettings) => Promise<FeSettings | null>;
}

interface EnabledLayerRowProps extends LayerRowFeSettingsProps {
  /** v2: groupIdは所属グループ表示用の導出値(flattenStackのビュー) */
  layer: LayerRuntime & { groupId?: string };
  /** カタログ上の名前・タグ・note */
  name: string;
  entry: LayerCatalogEntry | undefined;
  groups: LayerGroup[];
  /** 所属グループの色(縦バー表示)。未所属なら undefined */
  groupColor?: string;
  layerActions: LayerActions;
}

/**
 * 有効レイヤ行の2行レイアウト(設計doc §5)。
 * 1行目: [handle][eye][名前+タグ] [select][設定icon][close icon]
 * 2行目: [slider(mx-3)] [opacity% 右端]
 * 設定iconで LayerSettingsDialog を開く(行ローカルstate)。
 * sortableのattributes/listenersは行全体(EnabledLayerRowのwrapper)に付く。
 */
export const EnabledLayerRowContent: React.FC<EnabledLayerRowProps> = ({
  layer,
  name,
  entry,
  groups,
  groupColor,
  layerActions,
  feSettings,
  onFeSettingsChange,
}) => {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const opacityPct = Math.round(layer.opacity * 100);
  const tagLabel = entry?.tags[0] ? LAYER_TAG_LABELS[entry.tags[0]] : null;

  // 名前部分: 凡例ポップオーバー(description/legend)と note ツールチップは
  // LayerLegendPopover 共通ブロックに委譲
  const nameBlock = (
    <LayerLegendPopover
      name={name}
      entry={entry}
      nameClassName={cn('truncate text-xs', layer.visible ? 'text-text' : 'text-text-muted')}
    />
  );

  return (
    <div
      className={cn(
        'flex items-stretch gap-1.5 rounded-lg border border-border/80 bg-white/[0.03] px-1.5 py-1.5 select-none',
      )}
    >
      {groupColor && (
        <span
          className="w-1 shrink-0 self-stretch rounded-full"
          style={{ backgroundColor: groupColor }}
          title={groups.find((g) => g.id === layer.groupId)?.name}
        />
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {/* 1行目: 操作系 */}
        <div className="flex min-w-0 items-center gap-1.5">
          <DragHandle label={`${name}をドラッグ(順序変更・グループ移動・無効化)`} />
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={layer.visible ? `${name}を非表示` : `${name}を表示`}
            title={layer.visible ? '非表示にする' : '表示する'}
            className={cn(
              'shrink-0',
              layer.visible ? 'text-text' : 'text-text-muted/60 hover:text-text-muted',
            )}
            onClick={() => layerActions.setLayerVisible(layer.id, !layer.visible)}
          >
            {layer.visible ? <FaEye /> : <FaEyeSlash />}
          </Button>
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            {nameBlock}
            {tagLabel && (
              <Badge variant="secondary" className="h-4 shrink-0 px-1 text-[9px]">
                {tagLabel}
              </Badge>
            )}
          </div>
          {groups.length > 0 && (
            <select
              aria-label={`${name}のグループ`}
              title="グループ割当"
              value={layer.groupId ?? ''}
              onChange={(e) => layerActions.assignLayerGroup(layer.id, e.target.value || null)}
              className={cn(
                'h-5 max-w-24 shrink-0 rounded-md border border-border bg-white/[0.04] px-1',
                'text-[10px] text-text-muted outline-none focus:border-primary',
              )}
            >
              <option value="">グループなし</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`${name}の設定`}
            title="レイヤ設定"
            className="shrink-0 text-text-muted/70 hover:text-primary"
            onClick={() => setSettingsOpen(true)}
          >
            <FaGear />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`${name}を無効化`}
            title="無効(リスト)へ戻す"
            className="shrink-0 text-text-muted/70 hover:text-danger"
            onClick={() => layerActions.removeLayer(layer.id)}
          >
            <FaCircleXmark />
          </Button>
        </div>
        {/* 2行目: 不透明度スライダー+%表示 */}
        <div className="flex items-center gap-1">
          <Slider
            className="mx-3 min-w-0 grow"
            aria-label={`${name}の不透明度`}
            value={[opacityPct]}
            onValueChange={(vals) => {
              const v = Array.isArray(vals) ? vals[0] : vals;
              if (typeof v === 'number') layerActions.setLayerOpacity(layer.id, v / 100);
            }}
            min={0}
            max={100}
            step={1}
          />
          <span
            className="w-8 shrink-0 text-right text-[9px] tabular-nums text-text-muted"
            title="不透明度"
          >
            {opacityPct}%
          </span>
        </div>
      </div>
      <LayerSettingsDialog
        layerId={layer.id}
        feSettings={feSettings}
        onUpdate={onFeSettingsChange}
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
      />
    </div>
  );
};

/** 有効レイヤ行(並べ替え可能)。行全体でドラッグ可(ハンドル=即時/本体=長押し)。
 *  挿入はインジケータ+ドロップ時一括確定のため、元行の transform 演出は使わない */
export const EnabledLayerRow: React.FC<EnabledLayerRowProps> = (props) => {
  const { attributes, listeners, setNodeRef, isDragging } = useSortable({
    id: props.layer.id,
    data: { type: 'layer', groupId: props.layer.groupId },
  });
  return (
    <div
      ref={setNodeRef}
      data-layer-row={props.layer.id}
      className={cn(isDragging && 'opacity-40')}
      {...attributes}
      {...listeners}
    >
      <EnabledLayerRowContent {...props} />
    </div>
  );
};

/** ドラッグ中の有効行を DragOverlay に描くための静的コピー */
export const EnabledLayerRowOverlay: React.FC<EnabledLayerRowProps & { width?: number }> = ({
  width,
  ...props
}) => (
  <div
    style={width != null ? { width } : undefined}
    className="pointer-events-none rounded-lg ring-2 ring-primary/70 shadow-xl"
  >
    <EnabledLayerRowContent {...props} />
  </div>
);

interface DisabledLayerRowProps {
  entry: LayerCatalogEntry;
  layerActions?: LayerActions;
}

/** 無効レイヤ行本体。クリックまたは+で有効化。行本体の長押し/ハンドルで有効リストへ移動 */
export const DisabledLayerRowContent: React.FC<DisabledLayerRowProps> = ({
  entry,
  layerActions,
}) => (
  <div
    role="button"
    aria-label={`${entry.name}を有効化`}
    className={cn(
      'flex cursor-pointer items-center gap-1.5 rounded-lg border border-transparent px-1.5 py-1 select-none',
      'transition-colors hover:border-border/60 hover:bg-white/[0.04]',
    )}
    onClick={(e) => {
      // ドラッグ終了直後のclickで誤って有効化しない
      if (suppressClickAfterDrag()) return;
      layerActions?.addLayer(entry.id);
      e.stopPropagation();
    }}
  >
    <DragHandle label={`${entry.name}をドラッグ(有効化)`} />
    <LayerLegendPopover
      name={entry.name}
      entry={entry}
      nameClassName="min-w-0 flex-1 truncate text-xs text-text-muted"
    />
    <span className="flex shrink-0 items-center gap-1">
      {entry.tags.slice(0, 2).map((tag) => (
        <Badge key={tag} variant="outline" className="h-4 px-1 text-[9px]">
          {LAYER_TAG_LABELS[tag]}
        </Badge>
      ))}
    </span>
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label={`${entry.name}を追加`}
      title="有効リストへ追加"
      className="shrink-0 text-text-muted/70 hover:text-primary"
      onClick={(e) => {
        e.stopPropagation();
        layerActions?.addLayer(entry.id);
      }}
    >
      <FaPlus />
    </Button>
  </div>
);

export const DisabledLayerRow: React.FC<DisabledLayerRowProps> = (props) => {
  const { attributes, listeners, setNodeRef, isDragging } = useSortable({
    id: props.entry.id,
    data: { type: 'layer' },
  });
  return (
    <div
      ref={setNodeRef}
      data-layer-row={props.entry.id}
      className={cn(isDragging && 'opacity-40')}
      {...attributes}
      {...listeners}
    >
      <DisabledLayerRowContent {...props} />
    </div>
  );
};

/** ドラッグ中の無効行を DragOverlay に描くための静的コピー */
export const DisabledLayerRowOverlay: React.FC<{
  entry: LayerCatalogEntry;
  width?: number;
}> = ({ entry, width }) => (
  <div
    style={width != null ? { width } : undefined}
    className={cn(
      'pointer-events-none rounded-lg border border-border bg-panel px-1.5 py-1',
      'ring-2 ring-primary/70 shadow-xl',
    )}
  >
    <DisabledLayerRowContent entry={entry} layerActions={undefined} />
  </div>
);

/** ベース行の差し替えドロップダウン(基本地図リスト、バッジなし)。現行ベースはチェック表示 */
const BaseSwapMenu: React.FC<{ currentId: string; layerActions: LayerActions }> = ({
  currentId,
  layerActions,
}) => (
  <Menu>
    <MenuTrigger
      render={
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="基本地図を差し替え"
          title="基本地図を差し替え"
          className="shrink-0 text-text-muted/70 hover:text-primary"
        >
          <FaArrowRightArrowLeft />
        </Button>
      }
    />
    <MenuContent align="end">
      {baseEntries.map((e) => (
        <MenuItem
          key={e.id}
          onClick={() => layerActions.selectBase(e.id as BaseLayerId)}
          className={cn('gap-1.5', e.id === currentId && 'text-accent')}
        >
          {e.id === currentId ? (
            <FaCheck className="size-2.5 shrink-0 text-accent" />
          ) : (
            <span className="size-2.5 shrink-0" />
          )}
          <span className="min-w-0 truncate">{e.name}</span>
        </MenuItem>
      ))}
    </MenuContent>
  </Menu>
);

/**
 * ベース行。最下層固定のためドラッグ不可(ハンドルなし・破線枠)。
 * 差し替えは差し替えMenu / 無効リストからのDnD / 上部タブ。
 * 表示切替・不透明度・設定は一般行と共通。グループ割当は不可。
 */
export const BaseLayerRow: React.FC<EnabledLayerRowProps & { isSwapTarget?: boolean }> = ({
  layer,
  name,
  entry,
  layerActions,
  feSettings,
  onFeSettingsChange,
  isSwapTarget,
}) => {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const opacityPct = Math.round(layer.opacity * 100);

  return (
    <div
      className={cn(
        'flex items-stretch gap-1.5 rounded-lg border border-dashed border-border/80 bg-white/[0.03] px-1.5 py-1.5 select-none',
        'transition-shadow',
        isSwapTarget && 'ring-2 ring-accent',
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {/* 1行目: 操作系 */}
        <div className="flex min-w-0 items-center gap-1.5">
          <Badge
            variant="outline"
            className="h-4 shrink-0 border-accent/40 bg-accent/10 px-1 text-[9px] text-accent"
            title="ベースマップ(最下層固定)"
          >
            基本地図
          </Badge>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={layer.visible ? `${name}を非表示` : `${name}を表示`}
            title={layer.visible ? '非表示にする' : '表示する'}
            className={cn(
              'shrink-0',
              layer.visible ? 'text-text' : 'text-text-muted/60 hover:text-text-muted',
            )}
            onClick={() => layerActions.setLayerVisible(layer.id, !layer.visible)}
          >
            {layer.visible ? <FaEye /> : <FaEyeSlash />}
          </Button>
          <LayerLegendPopover
            name={name}
            entry={entry}
            nameClassName="min-w-0 flex-1 truncate text-xs text-text-muted"
          />
          <BaseSwapMenu currentId={layer.id} layerActions={layerActions} />
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`${name}の設定`}
            title="レイヤ設定"
            className="shrink-0 text-text-muted/70 hover:text-primary"
            onClick={() => setSettingsOpen(true)}
          >
            <FaGear />
          </Button>
        </div>
        {/* 2行目: 不透明度スライダー+%表示 */}
        <div className="flex items-center gap-1">
          <Slider
            className="mx-3 min-w-0 grow"
            aria-label={`${name}の不透明度`}
            value={[opacityPct]}
            onValueChange={(vals) => {
              const v = Array.isArray(vals) ? vals[0] : vals;
              if (typeof v === 'number') layerActions.setLayerOpacity(layer.id, v / 100);
            }}
            min={0}
            max={100}
            step={1}
          />
          <span
            className="w-8 shrink-0 text-right text-[9px] tabular-nums text-text-muted"
            title="不透明度"
          >
            {opacityPct}%
          </span>
        </div>
      </div>
      <LayerSettingsDialog
        layerId={layer.id}
        feSettings={feSettings}
        onUpdate={onFeSettingsChange}
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
      />
    </div>
  );
};

/**
 * 物件ピン行(最前面固定の特殊行。BaseLayerRow=最下層固定の対称)。
 * 検索結果の動的データのためスタック外で常駐し、表示切替と不透明度のみ
 * 操作可(ドラッグ/無効化/グループ参加は不可。カタログエントリが無いため
 * 設定モーダル・凡例ポップオーバーも無し)。
 */
export const PropertiesLayerRow: React.FC<{
  layer: LayerRuntime;
  layerActions: LayerActions;
}> = ({ layer, layerActions }) => {
  const opacityPct = Math.round(layer.opacity * 100);
  const name = '物件ピン';

  return (
    <div className="flex items-stretch gap-1.5 rounded-lg border border-dashed border-border/80 bg-white/[0.03] px-1.5 py-1.5 select-none">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {/* 1行目: 操作系 */}
        <div className="flex min-w-0 items-center gap-1.5">
          <Badge
            variant="outline"
            className="h-4 shrink-0 border-accent/40 bg-accent/10 px-1 text-[9px] text-accent"
            title="物件ピン(最前面固定)"
          >
            物件
          </Badge>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={layer.visible ? `${name}を非表示` : `${name}を表示`}
            title={layer.visible ? '非表示にする' : '表示する'}
            className={cn(
              'shrink-0',
              layer.visible ? 'text-text' : 'text-text-muted/60 hover:text-text-muted',
            )}
            onClick={() => layerActions.setPropertiesVisible(!layer.visible)}
          >
            {layer.visible ? <FaEye /> : <FaEyeSlash />}
          </Button>
          <span
            className="min-w-0 flex-1 truncate text-xs text-text-muted"
            title="サイドバーの検索結果に一致する物件ピン(最前面固定)"
          >
            {name}
          </span>
        </div>
        {/* 2行目: 不透明度スライダー+%表示 */}
        <div className="flex items-center gap-1">
          <Slider
            className="mx-3 min-w-0 grow"
            aria-label={`${name}の不透明度`}
            value={[opacityPct]}
            onValueChange={(vals) => {
              const v = Array.isArray(vals) ? vals[0] : vals;
              if (typeof v === 'number') layerActions.setPropertiesOpacity(v / 100);
            }}
            min={0}
            max={100}
            step={1}
          />
          <span
            className="w-8 shrink-0 text-right text-[9px] tabular-nums text-text-muted"
            title="不透明度"
          >
            {opacityPct}%
          </span>
        </div>
      </div>
    </div>
  );
};

/**
 * グループヘッダー(折りたたみ/名前inline編集/メンバー数/eye/不透明度/削除)。
 * ドラッグ: グリップ=即時、ヘッダー余白=長押し。名前ボタン・input は発火対象外
 * (クリックで編集可)。操作系子要素は stopDrag で伝播を止める
 */
export const GroupHeaderContent: React.FC<{
  group: LayerGroup;
  memberCount: number;
  color: string;
  collapsed: boolean;
  onToggleCollapsed?: () => void;
  layerActions?: LayerActions;
  dragBindings?: SortableBindings;
}> = ({ group, memberCount, color, collapsed, onToggleCollapsed, layerActions, dragBindings }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(group.name);

  /** ヘッダーにsortable listenersを付与するため、操作系子要素はドラッグ開始を止める */
  const stopDrag = (e: React.PointerEvent) => e.stopPropagation();

  const startEditing = () => {
    setDraft(group.name);
    setEditing(true);
  };
  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next && next !== group.name) layerActions?.renameGroup(group.id, next);
  };
  const cancel = () => {
    setEditing(false);
    setDraft(group.name);
  };

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-1.5 gap-y-1 rounded-lg border border-border/80 bg-white/[0.03] px-2 py-1.5 select-none',
        dragBindings && 'cursor-grab touch-none active:cursor-grabbing',
      )}
      {...(dragBindings?.attributes ?? {})}
      {...(dragBindings?.listeners ?? {})}
    >
      <span
        className="w-1 shrink-0 self-stretch rounded-full"
        style={{ backgroundColor: color }}
      />
      <DragHandle label={`${group.name}をドラッグ(並べ替え)`} />
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={collapsed ? `${group.name}を展開` : `${group.name}を折りたたむ`}
        aria-expanded={!collapsed}
        title={collapsed ? '展開' : '折りたたむ'}
        className="shrink-0 text-text-muted/70 hover:text-text"
        onPointerDown={stopDrag}
        onClick={() => onToggleCollapsed?.()}
      >
        <FaChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />
      </Button>
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onPointerDown={stopDrag}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            else if (e.key === 'Escape') cancel();
          }}
          aria-label="グループ名"
          className="h-6 min-w-0 flex-1 basis-20 rounded-md border border-primary bg-white/[0.04] px-1.5 text-xs text-text outline-none select-text"
        />
      ) : (
        <button
          type="button"
          onClick={startEditing}
          title="クリックで名前を編集"
          className="min-w-0 flex-1 basis-20 truncate text-left text-xs font-semibold text-text transition-colors hover:text-primary"
        >
          {group.name}
        </button>
      )}
      <Badge variant="secondary" className="h-4 shrink-0 px-1 text-[9px]" title="メンバー数">
        {memberCount}
      </Badge>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={`${group.name}の表示切替`}
        title={group.visible ? '非表示にする' : '表示する'}
        className={cn(
          'shrink-0',
          group.visible ? 'text-text' : 'text-text-muted/60 hover:text-text-muted',
        )}
        onPointerDown={stopDrag}
        onClick={() => layerActions?.setGroupVisible(group.id, !group.visible)}
      >
        {group.visible ? <FaEye /> : <FaEyeSlash />}
      </Button>
      <span className="flex w-16 shrink-0 items-center" onPointerDown={stopDrag}>
        <Slider
          className="w-full"
          aria-label={`${group.name}の不透明度`}
          value={[Math.round(group.opacity * 100)]}
          onValueChange={(vals) => {
            const v = Array.isArray(vals) ? vals[0] : vals;
            if (typeof v === 'number') layerActions?.setGroupOpacity(group.id, v / 100);
          }}
          min={0}
          max={100}
          step={1}
        />
      </span>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={`${group.name}を削除`}
        title="グループを削除(メンバーはスタックに残る)"
        className="shrink-0 text-text-muted/70 hover:text-danger"
        onPointerDown={stopDrag}
        onClick={() => layerActions?.removeGroup(group.id)}
      >
        <FaTrashCan />
      </Button>
    </div>
  );
};
