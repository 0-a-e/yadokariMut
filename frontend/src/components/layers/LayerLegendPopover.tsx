import React from 'react';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip.tsx';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover.tsx';
// Tooltip の render 先に渡す際は ref 転送のため Base UI プリミティブを直接使う
import { Popover as PopoverPrimitive } from '@base-ui/react/popover';
import { cn } from '@/lib/utils.ts';
import type { LayerCatalogEntry } from '../../lib/layers/types.ts';

interface LayerLegendPopoverProps {
  /** カタログ上のレイヤ名(aria-label とトリガ表示に使用) */
  name: string;
  /** カタログエントリ(description/legend/note/attribution の供給源) */
  entry: LayerCatalogEntry | undefined;
  /** 名前spanのクラス(truncate・有効/無効の色分けなど。ヘルプ装飾は内部で付与) */
  nameClassName?: string;
}

/**
 * レイヤ名部分に凡例ポップオーバー(説明+色見本+attribution)と
 * note ツールチップを付与する共通ブロック(LayerRow / DisabledLayerRow 共用)。
 * description/legend 持ちエントリは名前部分をトリガにホバー+クリック/フォーカスで開く。
 * どちらの情報も無いエントリは単なる名前 span を返す(呼び出し側で分岐不要)。
 */
export const LayerLegendPopover: React.FC<LayerLegendPopoverProps> = ({
  name,
  entry,
  nameClassName,
}) => {
  const note = entry?.note;
  const description = entry?.description;
  const legend = entry?.legend ?? [];
  const hasInfo = Boolean(description || legend.length > 0);

  const nameSpan = (
    <span
      className={cn(
        nameClassName,
        (note || hasInfo) &&
          'cursor-help underline decoration-dotted decoration-text-muted/60 underline-offset-2',
      )}
    >
      {name}
    </span>
  );

  // 凡例ポップオーバー(description/legend 持ちエントリ)。ホバーで開き、
  // クリック/Enter でも開閉する。note の Tooltip と併存するときは
  // 両 Root の下でトリガ同士を render 連鎖させ、1つの span に統合する
  // (Base UI の標準コンポジション。Root は DOM を描かない)
  const popoverTrigger = (
    <PopoverTrigger
      render={nameSpan}
      nativeButton={false}
      openOnHover
      delay={150}
      closeDelay={200}
      aria-label={`${name}の凡例`}
    />
  );
  const legendContent = (
    <PopoverContent aria-label={`${name}の凡例`}>
      {description && <p className="text-text">{description}</p>}
      {legend.length > 0 && (
        <ul className="flex flex-col gap-1">
          {legend.map((item) => (
            <li key={item.label} className="flex items-center gap-1.5">
              <span
                className="inline-block size-2.5 shrink-0 rounded-sm border border-white/30"
                style={{ backgroundColor: item.color }}
                aria-hidden="true"
              />
              <span className="text-text-muted">{item.label}</span>
            </li>
          ))}
        </ul>
      )}
      {/* attribution はカタログ内の固定文字列のみのため dangerouslySetInnerHTML を許容 */}
      {entry?.attribution && (
        <p
          className="text-[10px] leading-relaxed text-text-muted/80 [&_a]:underline"
          dangerouslySetInnerHTML={{ __html: entry.attribution }}
        />
      )}
    </PopoverContent>
  );

  if (hasInfo && note) {
    // 両方: Popover Root > Tooltip Root > (TooltipTrigger render → Popover Trigger > span)
    // Tooltip が render 先へ ref を渡すため、ここはラッパでなくプリミティブを使う
    return (
      <Popover>
        <Tooltip>
          <TooltipTrigger
            render={
              <PopoverPrimitive.Trigger
                render={nameSpan}
                nativeButton={false}
                openOnHover
                delay={150}
                closeDelay={200}
                aria-label={`${name}の凡例`}
              />
            }
          />
          <TooltipContent>{note}</TooltipContent>
        </Tooltip>
        {legendContent}
      </Popover>
    );
  }
  if (hasInfo) {
    return (
      <Popover>
        {popoverTrigger}
        {legendContent}
      </Popover>
    );
  }
  if (note) {
    return (
      <Tooltip>
        <TooltipTrigger render={nameSpan} />
        <TooltipContent>{note}</TooltipContent>
      </Tooltip>
    );
  }
  return nameSpan;
};
