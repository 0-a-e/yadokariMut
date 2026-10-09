/**
 * 物件画像のカルーセル(hextaUI)。スライド位置・読込エラーは内部 state で管理し、
 * クリックで Lightbox へ(onImageClick)。ページネーションはサムネイル列+枚数カウンタ。
 * メディアストア導入後は images=thumb variant(640px WebP)・fullImages=オリジナルを
 * 受け、ライトボックスには fullImages を渡す(未指定なら images と同一)。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselPrevious,
  CarouselNext,
  type CarouselApi,
} from '@/components/ui/carousel.tsx';
import { FaRegImage } from 'react-icons/fa6';
import { useHorizontalWheelNav } from '../../hooks/useHorizontalWheelNav.ts';
import { CarouselThumbnails } from '@/components/shared/CarouselThumbnails.tsx';
import { EmptyState } from '@/components/shared/EmptyState.tsx';
import { cn } from '@/lib/utils.ts';

interface ImageCarouselProps {
  /** カルーセル表示用 URL 列(メディアストア導入後は thumb variant 優先) */
  images: string[];
  /**
   * ライトボックスへ渡すオリジナル URL 列(メディアストア導入後は media オリジナル)。
   * 未指定なら images をそのまま渡す(従来動作・呼び出し元の後方互換)。
   */
  fullImages?: string[];
  propertyId: number;
  onImageClick: (images: string[], index: number) => void;
}

export const ImageCarousel: React.FC<ImageCarouselProps> = ({
  images,
  fullImages,
  propertyId,
  onImageClick,
}) => {
  const [imageError, setImageError] = useState<{ [key: number]: boolean }>({});
  const [carouselApi, setCarouselApi] = useState<CarouselApi>();
  const rootRef = useRef<HTMLDivElement>(null);

  // 物件切替・URL 列差し替え(詳細 API 到着で media URL へ変化)時に読込エラーを破棄
  useEffect(() => {
    setImageError({});
  }, [propertyId, images]);

  useEffect(() => {
    if (!carouselApi) return;
    carouselApi.scrollTo(0, true);
  }, [propertyId, carouselApi]);

  // デスクトップの横倒しホイール / 横スワイプでスライダを送る
  const scrollPrevByWheel = useCallback(() => carouselApi?.scrollPrev(), [carouselApi]);
  const scrollNextByWheel = useCallback(() => carouselApi?.scrollNext(), [carouselApi]);
  useHorizontalWheelNav({
    target: rootRef.current ?? null,
    enabled: images.length > 1,
    onPrev: scrollPrevByWheel,
    onNext: scrollNextByWheel,
  });

  return (
    /* Image carousel — scrolls with content; swipe-enabled via native scroll-snap */
    <div
      ref={rootRef}
      className={cn(
        'group relative w-full shrink-0 bg-white/[0.05] overflow-hidden',
        'h-[clamp(200px,32dvh,460px)]',
        'max-md:h-[clamp(160px,28dvh,240px)]',
        // carousel viewport / track need explicit height from the clamp container
        '[&_[data-slot=carousel]]:size-full',
        '[&_[data-slot=carousel-content]]:size-full',
        '[&_[data-slot=carousel-container]]:h-full',
        '[&_[data-slot=carousel-item]]:h-full'
      )}
    >
      {images.length === 0 ? (
        <EmptyState
          icon={FaRegImage}
          iconClassName="text-2xl text-primary"
          message="画像がありません"
          className="size-full justify-center gap-2 bg-gradient-to-br from-[#1e1e2e] to-[#11111b] not-italic"
        />
      ) : (
        <Carousel
          spacing="none"
          rewind={images.length > 1}
          setApi={setCarouselApi}
          className="size-full"
        >
          {/* viewport の -m-1/p-1(フォーカスリング余白)は full-bleed 画像のため無効化 */}
          <CarouselContent viewportClassName="-m-0 p-0" className="h-full -ms-0">
            {images.map((url, index) => (
              <CarouselItem key={index} className="basis-full h-full ps-0">
                {imageError[index] ? (
                  <EmptyState
                    icon={FaRegImage}
                    iconClassName="text-2xl text-primary"
                    message="画像の読み込みに失敗しました"
                    className="size-full justify-center gap-2 bg-gradient-to-br from-[#1e1e2e] to-[#11111b] not-italic"
                  />
                ) : (
                  <button
                    type="button"
                    className="block size-full cursor-pointer border-0 p-0 bg-cover bg-center"
                    style={{ backgroundImage: `url('${url}')` }}
                    aria-label={`画像 ${index + 1} を拡大表示`}
                    onClick={() => onImageClick(fullImages ?? images, index)}
                  >
                    {/* preload / error detection */}
                    <img
                      src={url}
                      alt=""
                      className="sr-only"
                      onError={() =>
                        setImageError((prev) => ({ ...prev, [index]: true }))
                      }
                    />
                  </button>
                )}
              </CarouselItem>
            ))}
          </CarouselContent>

          {images.length > 1 && (
            <>
              {/* 押下時は移動させず背景色でフィードバックする (button.tsx の active:translate-y-px を ! で打ち消す) */}
              <CarouselPrevious
                variant="ghost"
                size="icon"
                className="left-3 size-9 bg-black/60 border border-white/20 text-white opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto z-10 hover:bg-primary hover:border-accent hover:scale-110 active:translate-y-0! active:bg-primary/70 active:border-accent disabled:opacity-0"
              />
              <CarouselNext
                variant="ghost"
                size="icon"
                className="right-3 size-9 bg-black/60 border border-white/20 text-white opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto z-10 hover:bg-primary hover:border-accent hover:scale-110 active:translate-y-0! active:bg-primary/70 active:border-accent disabled:opacity-0"
              />
              <CarouselThumbnails images={images} autoHide />
            </>
          )}
        </Carousel>
      )}
    </div>
  );
};
