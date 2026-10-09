/**
 * カルーセルのサムネイルページネーション。detail/ImageCarousel と LightboxModal で共用。
 * hextaUI Carousel の中に置く絶対配置前提で、位置は既定値(bottom-3 中央)を className で上書きする。
 * 列上中央に白文字黒影の xx/xx カウンタを重ねる。選択中サムネイルはアクセントリング+不透明で強調
 * (hextaUI の data-active は「視界内」を意味し選択状態ではないため強調は自前で行う)。
 * サムネイルには本画像 URL をそのまま使う(詳細カルーセルと同一 URL のためキャッシュで二重フェッチなし)。
 *
 * autoHide(詳細パネル用): 非ホバー かつ 3 秒無操作で帯を画像下端外へ格納し、カウンタだけ
 * 帯のあった位置近くまで下げて残す。操作(select 変化)or ホバーで復帰する。
 * マウスホイール(縦回転・横倒しとも)はストリップの横スクロールに変換し、
 * stopPropagation でスライダ送り(useHorizontalWheelNav)への伝播を遮ってサムネイルを優先する。
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  CarouselCounter,
  CarouselThumbnail,
  CarouselThumbnails as CarouselThumbnailsBase,
  useCarousel,
} from '@/components/ui/carousel.tsx';
import { cn } from '@/lib/utils.ts';

/** autoHide 時に操作なしとみなして帯を格納するまでの時間 (ms) */
export const IDLE_HIDE_MS = 3000;

/**
 * ホイール入力をサムネイル列の横スクロール量へ変換する(縦回転・横倒しの双方)。
 * 無入力(delta が 0)は null で何もしない — トラックパッドの微小ノイズで
 * preventDefault が発火し、ページの縦スクロールまで奪うのを避ける意図。
 */
export function thumbnailWheelDelta(e: { deltaY: number; deltaX: number }): number | null {
  if (e.deltaY === 0 && e.deltaX === 0) return null;
  return e.deltaY + e.deltaX;
}

interface CarouselThumbnailsProps {
  /** サムネイルに表示する画像 URL 群 */
  images: string[];
  /** 配置オーバーライド(絶対配置の位置や幅上限を変える) */
  className?: string;
  /** サムネイル1枚のサイズクラス。既定は size-10(max-md:size-8) */
  thumbnailClassName?: string;
  /** 詳細パネル用: 非ホバー かつ IDLE_HIDE_MS 無操作で帯を格納する */
  autoHide?: boolean;
}

export const CarouselThumbnails: React.FC<CarouselThumbnailsProps> = ({
  images, className, thumbnailClassName, autoHide = false,
}) => {
  const { selectedIndex: selected } = useCarousel();
  const rootRef = useRef<HTMLDivElement>(null);
  const [idle, setIdle] = useState(false);
  const hidden = autoHide && idle;

  // 操作(select 変化)ごとに無操作タイマーを起こす。スワイプ・ホイール送り・矢印・
  // サムネイルクリックはすべて select に還元される。ホバー中の常時表示は group-hover CSS 側で担保
  useEffect(() => {
    if (!autoHide) return;
    setIdle(false);
    const timer = window.setTimeout(() => setIdle(true), IDLE_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [autoHide, selected]);

  // ストリップのホイール(縦回転・横倒しとも)を横スクロールへ変換。
  // React の onWheel は passive 制御が不確実なため手動 addEventListener。
  // スライダ送りはバブリング段階のリスナーなので伝播を止めれば完全に抑えられる
  useEffect(() => {
    const strip = rootRef.current?.querySelector<HTMLElement>('[data-slot="carousel-thumbnails"]');
    if (!strip) return;
    const onWheel = (e: WheelEvent) => {
      const delta = thumbnailWheelDelta(e);
      if (delta === null) return;
      e.preventDefault();
      e.stopPropagation();
      strip.scrollBy({ left: delta });
    };
    strip.addEventListener('wheel', onWheel, { passive: false });
    return () => strip.removeEventListener('wheel', onWheel);
  }, []);

  // 格納は帯を下へ滑らせつつフェード(ルート overflow-hidden 内で視覚消滅)。
  // 透明化中もホバー検出を生かすため pointer-events は保持し、group-hover で強制復帰する
  return (
    <div
      ref={rootRef}
      className={cn(
        'absolute bottom-3 left-1/2 -translate-x-1/2 z-10 max-w-[min(92%,480px)]',
        className,
      )}
    >
      {/* カウンタ: 白文字黒影。格納時(autoHide アイドル)は帯のあった位置近くまで下げて残す。
          translate-y-12 は帯高さ(サムネイル size-10 + p-1 = 3rem)前提の値。thumbnailClassName を
          変える場合は同時に見直すこと。帯と完全同期させるため group-hover 復帰も共通(Tailwind の
          variant は基本ユーティリティより後に出力されるため、hidden でもホバー中は上位置が勝つ) */}
      <CarouselCounter
        className={cn(
          'absolute -top-6.5 left-1/2 -translate-x-1/2 text-xs! text-white!',
          'transition-transform duration-300 ease-out-quint',
          autoHide && 'group-hover:translate-y-0',
          '[text-shadow:0_1px_3px_rgba(0,0,0,0.9),0_0_10px_rgba(0,0,0,0.65)]',
          hidden && 'translate-y-12',
        )}
      />
      <div
        className={cn(
          'bg-black/40 rounded-[10px] backdrop-blur-glass p-1',
          'transition-[transform,opacity] duration-300 ease-out-quint',
          autoHide && 'group-hover:translate-y-0 group-hover:opacity-100',
          hidden && 'translate-y-[calc(100%+0.75rem)] opacity-0',
        )}
      >
        <CarouselThumbnailsBase>
          {images.map((url, index) => (
            <CarouselThumbnail
              key={index}
              index={index}
              className={cn(
                'size-10 max-md:size-8',
                index === selected && 'opacity-100!',
                thumbnailClassName,
              )}
            >
              {/* 選択ハイライト(data-active の inView リングと競合しない子要素で重ねる) */}
              {index === selected && (
                <span aria-hidden className="pointer-events-none absolute inset-0 rounded-[inherit] ring-2 ring-accent" />
              )}
              <img
                src={url}
                alt=""
                className="pointer-events-none size-full object-cover select-none"
                draggable={false}
              />
            </CarouselThumbnail>
          ))}
        </CarouselThumbnailsBase>
      </div>
    </div>
  );
};
