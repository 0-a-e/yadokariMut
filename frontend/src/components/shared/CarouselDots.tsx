/**
 * カルーセルのドットページネーション。detail/ImageCarousel と LightboxModal で共用。
 * Carousel の中に置く絶対配置前提で、位置は既定値(bottom-3 中央)を className で上書きする。
 */
import React from 'react';
import { cn } from '@/lib/utils.ts';

interface CarouselDotsProps {
  /** 総スライド枚数 */
  count: number;
  /** アクティブなスライド番号(0始まり) */
  activeIndex: number;
  /** ドット押下でそのスライドへ移動する */
  onSelect: (index: number) => void;
  className?: string;
}

export const CarouselDots: React.FC<CarouselDotsProps> = ({
  count, activeIndex, onSelect, className,
}) => {
  return (
    <div className={cn(
      'absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1.5 z-10 bg-black/40 py-1 px-2 rounded-[10px]',
      className,
    )}>
      {Array.from({ length: count }, (_, index) => (
        <button
          key={index}
          type="button"
          aria-label={`画像 ${index + 1}`}
          className={cn(
            'size-1.5 rounded-full bg-white/40 cursor-pointer transition-all duration-200 border-0 p-0',
            index === activeIndex && '!bg-accent scale-125',
          )}
          onClick={() => onSelect(index)}
        />
      ))}
    </div>
  );
};
