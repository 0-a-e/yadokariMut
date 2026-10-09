import React, { useCallback, useEffect, useState } from 'react';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { Button } from '@/components/ui/button.tsx';
import { FaChevronLeft, FaChevronRight } from 'react-icons/fa6';
import { Carousel, CarouselContent, CarouselItem, type CarouselApi } from '@/components/ui/carousel.tsx';
import { CarouselThumbnails } from '@/components/shared/CarouselThumbnails.tsx';
import { useHorizontalWheelNav } from '../../hooks/useHorizontalWheelNav.ts';
import { useSwipeDismiss } from '../../hooks/useSwipeDismiss.ts';

/** ヒントの表示時間(ms)。その後 HINT_FADE_MS かけてフェードアウトする */
const HINT_VISIBLE_MS = 1500;
const HINT_FADE_MS = 700;

interface LightboxModalProps {
  isOpen: boolean;
  images: string[];
  /** 開いた直後に表示するスライド番号。開始後のインデックスはCarousel(内部)が管理する */
  initialIndex: number;
  title: string;
  onClose: () => void;
}

export const LightboxModal: React.FC<LightboxModalProps> = ({
  isOpen, images, initialIndex, title, onClose,
}) => {
  const [carouselApi, setCarouselApi] = useState<CarouselApi>();
  const [slideIndex, setSlideIndex] = useState(initialIndex);
  /** 画像ごとのアスペクト比(w/h)。ステージを現スライドの寸法に密着させるのに使う */
  const [aspects, setAspects] = useState<Record<number, number>>({});

  // 全画像の自然寸法を先読み(ステージ追従+隣接画像のプリロードを兼ねる)
  useEffect(() => {
    if (!isOpen) return;
    let alive = true;
    images.forEach((src, i) => {
      const img = new Image();
      img.onload = () => {
        if (alive && img.naturalWidth > 0) {
          setAspects((prev) => ({ ...prev, [i]: img.naturalWidth / img.naturalHeight }));
        }
      };
      img.src = src;
    });
    return () => { alive = false; };
  }, [isOpen, images]);

  // 閉じたら全面アンマウントされるため、defaultIndexは毎回のオープンで効く
  const scrollPrev = useCallback(() => carouselApi?.scrollPrev(), [carouselApi]);
  const scrollNext = useCallback(() => carouselApi?.scrollNext(), [carouselApi]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      // フォーカス位置に依存せず矢印で送る。キャプチャ段階で先に処理して伝播を止める
      // (CarouselルートのonKeyDownCaptureとの二重送り防止)
      e.preventDefault();
      e.stopPropagation();
      if (e.key === 'ArrowRight') scrollNext();
      else scrollPrev();
    };
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [isOpen, onClose, scrollPrev, scrollNext]);

  // モーダル表示中はどこにカーソルがあっても横倒しホイールで送れるようにする
  useHorizontalWheelNav({
    target: typeof document === 'undefined' ? null : document,
    enabled: isOpen && images.length > 1,
    onPrev: scrollPrev,
    onNext: scrollNext,
  });

  // ── モバイル: 上下スワイプで閉じる(Xは廃止) ──
  // 横スクロール(scroll-snap + touch-action既定)が横ドラッグを握るため縦スワイプとの
  // 共存は dominance ゲートで足りる。ステージは fadeWithDrag で指に追従して薄れる
  const swipe = useSwipeDismiss({
    enabled: isOpen,
    direction: 'vertical',
    fadeWithDrag: true,
    onDismiss: onClose,
  });

  // 「上下スワイプで閉じる」ヒント。開くたびに表示 → 一定時間後にフェードアウト。
  // visible → fading(opacity 遷移中) → hidden(アンマウント)
  const [hintState, setHintState] = useState<'hidden' | 'visible' | 'fading'>('hidden');
  useEffect(() => {
    if (!isOpen) {
      setHintState('hidden');
      return;
    }
    setHintState('visible');
    const fadeTimer = window.setTimeout(
      () => setHintState('fading'),
      HINT_VISIBLE_MS,
    );
    const hideTimer = window.setTimeout(
      () => setHintState('hidden'),
      HINT_VISIBLE_MS + HINT_FADE_MS,
    );
    return () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(hideTimer);
    };
  }, [isOpen]);
  // スワイプを始めたらヒントは即隠す
  useEffect(() => {
    if (swipe.isDragging) setHintState('hidden');
  }, [swipe.isDragging]);

  if (!isOpen || images.length === 0) return null;

  return (
    <DialogPrimitive.Root open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-[9998] bg-[rgba(13,14,18,0.95)] backdrop-blur-[12px] data-open:animate-in data-open:fade-in-0"
        />
        <DialogPrimitive.Popup
          className="fixed inset-0 z-[9999] flex items-center justify-center outline-none overscroll-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95"
          // 枠外(ステージ外)クリックで閉じる。全画面Popup自体がクリック面になるため
          // Backdropではなくこちらで受ける(targetガードで子要素クリックは弾く)
          onClick={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
        >
          {/* スワイプ中の操作を妨げないようヒントは pointer-events-none */}
          {hintState !== 'hidden' && (
            <div
              aria-hidden
              className={`hidden max-md:block absolute top-[calc(env(safe-area-inset-top,0px)+0.75rem)] left-1/2 -translate-x-1/2 z-20 pointer-events-none text-white text-[13px] font-medium tracking-wide [text-shadow:0_1px_3px_rgba(0,0,0,0.9),0_0_10px_rgba(0,0,0,0.65)] transition-opacity duration-700 ${
                hintState === 'fading' ? 'opacity-0' : 'opacity-100'
              }`}
            >
              上下スワイプで閉じる
            </div>
          )}
          {/* モバイルではステージが全画面になるためmax-wを解除。
              スワイプdismissはこのステージ wrapper を丸ごと動かす */}
          <div
            ref={swipe.targetRef}
            {...swipe.bind}
            className={`relative max-w-[90%] max-md:max-w-full flex flex-col items-center ${
              swipe.isDragging ? 'select-none' : ''
            }`}
          >
            {/* ステージは現スライドのアスペクト比に追従し、画像全体が収まる最大サイズまで
                拡大する(90vw×80dvh上限)。枠内に余白が出ない。幅=高さ制約とアスペクトから
                導出し、--lb-arの遷移で切替時に枠がモーフする。モバイルは全画面で枠・角丸・影なし */}
            <Carousel
              spacing="none"
              rewind={images.length > 1}
              defaultIndex={initialIndex}
              onIndexChange={setSlideIndex}
              setApi={setCarouselApi}
              style={{ '--lb-ar': aspects[slideIndex] ?? 1.5 } as React.CSSProperties}
              className="[--lb-ar:1.5] w-[min(90vw,calc(80dvh*var(--lb-ar)))] max-w-[90%] aspect-[var(--lb-ar)] overflow-hidden rounded-lg border border-border bg-black/40 shadow-[0_0_30px_rgba(0,0,0,0.8)] transition-[--lb-ar] duration-300 ease-out [&_[data-slot=carousel-content]]:h-full [&_[data-slot=carousel-container]]:h-full [&_[data-slot=carousel-item]]:h-full max-md:w-full max-md:max-w-full max-md:h-dvh max-md:rounded-none max-md:border-0 max-md:shadow-none"
            >
              {/* viewport の -m-1/p-1(フォーカスリング余白)は full-bleed 画像のため無効化 */}
              <CarouselContent viewportClassName="-m-0 p-0" className="h-full">
                {images.map((url, index) => (
                  <CarouselItem key={index} className="basis-full h-full ps-0 flex items-center justify-center">
                    {/* ステージが現スライドのアスペクトに一致するため現画像は余白なしで満たる。
                        object-containは隣接スライド(異アスペクト)のスライドイン中のガード */}
                    <img
                      src={url}
                      alt={`${title} - ${index + 1}`}
                      className="size-full object-contain select-none"
                      draggable={false}
                    />
                  </CarouselItem>
                ))}
              </CarouselContent>
              {images.length > 1 && (
                <>
                  {/* 左右ボタンはデスクトップのみ。モバイルはスワイプ+サムネイル */}
                  {/* 押下時は移動させず背景色でフィードバックする (button.tsx の active:translate-y-px を ! で打ち消す) */}
                  <Button
                    variant="ghost"
                    size="icon-lg"
                    className="absolute inset-y-0 my-auto left-3 max-md:hidden bg-[rgba(22,24,33,0.6)] backdrop-blur-glass border border-border text-white w-12 h-12 rounded-full hover:bg-primary hover:border-accent hover:scale-110 active:translate-y-0! active:bg-primary/70 active:border-accent z-10"
                    onClick={scrollPrev}
                  >
                    <FaChevronLeft />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-lg"
                    className="absolute inset-y-0 my-auto right-3 max-md:hidden bg-[rgba(22,24,33,0.6)] backdrop-blur-glass border border-border text-white w-12 h-12 rounded-full hover:bg-primary hover:border-accent hover:scale-110 active:translate-y-0! active:bg-primary/70 active:border-accent z-10"
                    onClick={scrollNext}
                  >
                    <FaChevronRight />
                  </Button>
                  {/* 下部固定サムネイル+枚数カウンタはモバイル/PC 共通(PC もモバイルと同じ仕様ベース) */}
                  <CarouselThumbnails
                    images={images}
                    className="bottom-[calc(env(safe-area-inset-bottom,0px)+0.75rem)]"
                  />
                </>
              )}
            </Carousel>
            {/* 物件名/建物名は画像上部(画像外)に PC のみ(モバイルは「上下スワイプで閉じる」ヒントのみ) */}
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 hidden md:block text-white text-sm font-medium [text-shadow:0_2px_4px_rgba(0,0,0,0.8)] whitespace-nowrap">
              {title}
            </div>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
};
