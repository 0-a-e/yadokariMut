import React, { useState } from 'react';
import { FaChevronDown } from 'react-icons/fa6';
import { cn } from '@/lib/utils.ts';
import { catalogById } from '../../lib/layers/catalog.ts';
import { effectiveRuntimeList } from '../../lib/layers/state.ts';
import type {
  LayerCatalogEntry,
  LayerConfigState,
  LegendEntry,
} from '../../lib/layers/types.ts';
import { useIsMobile } from '../../hooks/useIsMobile.ts';

/** 凡例の色見本(ジオメトリ種に合わせた形状) */
const LegendSwatch: React.FC<{ entry: LegendEntry }> = ({ entry }) => {
  const shape = entry.shape ?? 'square';
  if (shape === 'circle') {
    return (
      <span
        className="inline-block size-2.5 shrink-0 rounded-full border border-white/30"
        style={{ backgroundColor: entry.color }}
        aria-hidden="true"
      />
    );
  }
  if (shape === 'line') {
    return (
      <span
        className="inline-block h-[3px] w-4 shrink-0 rounded-full"
        style={{ backgroundColor: entry.color }}
        aria-hidden="true"
      />
    );
  }
  return (
    <span
      className="inline-block size-2.5 shrink-0 rounded-sm border border-white/30"
      style={{ backgroundColor: entry.color }}
      aria-hidden="true"
    />
  );
};

/** レイヤ単位の凡例ブロック(折りたたみ可能) */
const LayerLegendBlock: React.FC<{
  entry: LayerCatalogEntry;
  defaultOpen: boolean;
}> = ({ entry, defaultOpen }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-md border border-border/70 bg-white/[0.03]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 px-1.5 py-1 text-left"
      >
        <FaChevronDown
          className={cn(
            'size-2.5 shrink-0 text-text-muted transition-transform',
            !open && '-rotate-90',
          )}
        />
        <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-text">
          {entry.name}
        </span>
      </button>
      {open && (
        <ul className="m-0 flex flex-col gap-0.5 px-2 pb-1.5 pt-0.5">
          {(entry.legend ?? []).map((item) => (
            <li key={item.label} className="flex items-center gap-1.5">
              <LegendSwatch entry={item} />
              <span className="text-[10px] leading-tight text-text-muted">{item.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

/**
 * 地図上凡例コントロール(左下)。
 * 表示中(visibleかつ実効不透明度>0)のレイヤのうち凡例定義(legend)を持つ
 * ものをスタック順(前面のレイヤが上)に列挙する。凡例データの正本は
 * カタログ側で、レイヤ名ホバーの凡例ポップオーバーと同じ定義を共有する。
 * 物件ピン(properties)はカタログエントリを持たないため自動的に対象外。
 */
export const MapLegendControl: React.FC<{ config: LayerConfigState }> = ({ config }) => {
  // モバイルでは画面を狭めないよう初期状態で全ブロック折りたたむ(開閉は随時可)
  const isMobile = useIsMobile();
  const entries = effectiveRuntimeList(config)
    .filter((layer) => layer.visible && layer.opacity > 0)
    .map((layer) => catalogById.get(layer.id))
    .filter(
      (entry): entry is LayerCatalogEntry => entry != null && (entry.legend?.length ?? 0) > 0,
    );

  if (entries.length === 0) return null;
  return (
    <div
      aria-label="地図レイヤ凡例"
      className="absolute bottom-3 left-3 z-[1200] flex max-h-[45%] w-56 flex-col gap-1 overflow-y-auto rounded-lg border border-border bg-bg p-1.5 shadow-md"
    >
      {entries.map((entry) => (
        <LayerLegendBlock key={entry.id} entry={entry} defaultOpen={!isMobile} />
      ))}
    </div>
  );
};
