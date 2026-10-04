import React, { useCallback, useEffect, useState } from 'react';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { Button } from '@/components/ui/button.tsx';
import { FaXmark, FaChevronLeft, FaChevronRight } from 'react-icons/fa6';
import { Carousel, CarouselContent, CarouselItem, type CarouselApi } from '@/components/ui/carousel.tsx';
import { CarouselDots } from '@/components/shared/CarouselDots.tsx';
import { useHorizontalWheelNav } from '../../hooks/useHorizontalWheelNav.ts';

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

  // 閉じたら全面アンマウントされるため、startIndexは毎回のオープンで効く
  const scrollPrev = useCallback(() => carouselApi?.scrollPrev(), [carouselApi]);
  const scrollNext = useCallback(() => carouselApi?.scrollNext(), [carouselApi]);

  // emblaの選択スナップ → カウンタ表示
  useEffect(() => {
    if (!carouselApi) return;
    setSlideIndex(carouselApi.selectedScrollSnap());
    const onSelect = (api: NonNullable<CarouselApi>) => setSlideIndex(api.selectedScrollSnap());
    carouselApi.on('select', onSelect);
    return () => { carouselApi.off('select', onSelect); };
  }, [carouselApi]);

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

  if (!isOpen || images.length === 0) return null;

  return (
    <DialogPrimitive.Root open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-[9998] bg-[rgba(13,14,18,0.95)] backdrop-blur-[12px] data-open:animate-in data-open:fade-in-0"
        />
        <DialogPrimitive.Popup
          className="fixed inset-0 z-[9999] flex items-center justify-center outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95"
          // 枠外(ステージ外)クリックで閉じる。全画面Popup自体がクリック面になるため
          // Backdropではなくこちらで受ける(targetガードで子要素クリックは弾く)
          onClick={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
        >
          {/* モバイルではステージが全画面になるためmax-wを解除 */}
          <div className="relative max-w-[90%] max-md:max-w-full flex flex-col items-center">
            {/* Xはモバイルのみ(デスクトップは枠外クリック/Escで閉じる) */}
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-[calc(env(safe-area-inset-top,0px)+0.5rem)] right-[calc(env(safe-area-inset-right,0px)+0.5rem)] md:hidden z-10 size-9 rounded-full bg-black/60 border border-white/20 text-white hover:bg-primary hover:border-accent active:translate-y-0! active:bg-primary/70 active:border-accent"
              onClick={onClose}
            >
              <FaXmark />
            </Button>
            {/* ステージは現スライドのアスペクト比に追従し、画像全体が収まる最大サイズまで
                拡大する(90vw×80dvh上限)。枠内に余白が出ない。幅=高さ制約とアスペクトから
                導出し、--lb-arの遷移で切替時に枠がモーフする。モバイルは全画面で枠・角丸・影なし */}
            <Carousel
              setApi={setCarouselApi}
              opts={{ loop: images.length > 1, startIndex: initialIndex, align: 'start' }}
              style={{ '--lb-ar': aspects[slideIndex] ?? 1.5 } as React.CSSProperties}
              className="[--lb-ar:1.5] w-[min(90vw,calc(80dvh*var(--lb-ar)))] max-w-[90%] aspect-[var(--lb-ar)] overflow-hidden rounded-lg border border-border bg-black/40 shadow-[0_0_30px_rgba(0,0,0,0.8)] transition-[--lb-ar] duration-300 ease-out [&_[data-slot=carousel-content]]:h-full max-md:w-full max-md:max-w-full max-md:h-dvh max-md:rounded-none max-md:border-0 max-md:shadow-none"
            >
              <CarouselContent className="h-full ml-0">
                {images.map((url, index) => (
                  <CarouselItem key={index} className="pl-0 basis-full h-full flex items-center justify-center">
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
                  {/* 左右ボタンはデスクトップのみ。モバイルはスワイプ+ドット */}
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
                  <CarouselDots
                    count={images.length}
                    activeIndex={slideIndex}
                    onSelect={(index) => carouselApi?.scrollTo(index)}
                    className="md:hidden bottom-[calc(env(safe-area-inset-bottom,0px)+0.75rem)]"
                  />
                </>
              )}
            </Carousel>
            {/* 物件名+カウンタはデスクトップのみ(モバイルはドットで代替) */}
            <div className="mt-4 max-md:hidden text-text text-sm font-medium text-center [text-shadow:0_2px_4px_rgba(0,0,0,0.8)]">
              {title} ({slideIndex + 1} / {images.length})
            </div>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
};
