/**
 * 物件画像のカルーセル(embla)。スライド位置・読込エラーは内部 state で管理し、
 * クリックで Lightbox へ(onImageClick)。
 */
import React, { useCallback, useEffect, useState } from 'react';
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
import { CarouselDots } from '@/components/shared/CarouselDots.tsx';
import { cn } from '@/lib/utils.ts';

interface ImageCarouselProps {
  images: string[];
  propertyId: number;
  onImageClick: (images: string[], index: number) => void;
}

export const ImageCarousel: React.FC<ImageCarouselProps> = ({
  images,
  propertyId,
  onImageClick,
}) => {
  const [slideIndex, setSlideIndex] = useState(0);
  const [imageError, setImageError] = useState<{ [key: number]: boolean }>({});
  const [carouselApi, setCarouselApi] = useState<CarouselApi>();

  useEffect(() => {
    setSlideIndex(0);
    setImageError({});
  }, [propertyId]);

  useEffect(() => {
    if (!carouselApi) return;
    const onSelect = () => setSlideIndex(carouselApi.selectedScrollSnap());
    onSelect();
    carouselApi.on('select', onSelect);
    carouselApi.on('reInit', onSelect);
    return () => {
      carouselApi.off('select', onSelect);
      carouselApi.off('reInit', onSelect);
    };
  }, [carouselApi]);

  useEffect(() => {
    if (!carouselApi) return;
    carouselApi.scrollTo(0, true);
  }, [propertyId, carouselApi]);

  // デスクトップの横倒しホイール / 横スワイプでスライダを送る
  const scrollPrevByWheel = useCallback(() => carouselApi?.scrollPrev(), [carouselApi]);
  const scrollNextByWheel = useCallback(() => carouselApi?.scrollNext(), [carouselApi]);
  useHorizontalWheelNav({
    target: carouselApi?.rootNode() ?? null,
    enabled: images.length > 1,
    onPrev: scrollPrevByWheel,
    onNext: scrollNextByWheel,
  });

  const handleDotClick = useCallback(
    (index: number) => {
      carouselApi?.scrollTo(index);
    },
    [carouselApi]
  );

  return (
    /* Image carousel — scrolls with content; swipe-enabled via embla */
    <div
      className={cn(
        'group relative w-full shrink-0 bg-white/[0.05] overflow-hidden',
        'h-[clamp(200px,32dvh,460px)]',
        'max-md:h-[clamp(160px,28dvh,240px)]',
        // embla viewport / track need explicit height from the clamp container
        '[&_[data-slot=carousel]]:size-full',
        '[&_[data-slot=carousel-content]]:size-full',
        '[&_[data-slot=carousel-item]]:h-full'
      )}
    >
      {images.length === 0 ? (
        <div className="flex size-full flex-col items-center justify-center gap-2 bg-gradient-to-br from-[#1e1e2e] to-[#11111b] text-text-muted text-sm">
          <FaRegImage className="text-2xl text-primary" />
          <span>画像がありません</span>
        </div>
      ) : (
        <Carousel
          opts={{ loop: images.length > 1, align: 'start' }}
          setApi={setCarouselApi}
          className="size-full"
        >
          <CarouselContent className="-ml-0 h-full">
            {images.map((url, index) => (
              <CarouselItem key={index} className="pl-0 basis-full h-full">
                {imageError[index] ? (
                  <div className="flex size-full flex-col items-center justify-center gap-2 bg-gradient-to-br from-[#1e1e2e] to-[#11111b] text-text-muted text-sm">
                    <FaRegImage className="text-2xl text-primary" />
                    <span>画像の読み込みに失敗しました</span>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="block size-full cursor-pointer border-0 p-0 bg-cover bg-center"
                    style={{ backgroundImage: `url('${url}')` }}
                    aria-label={`画像 ${index + 1} を拡大表示`}
                    onClick={() => onImageClick(images, index)}
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
              <CarouselDots
                count={images.length}
                activeIndex={slideIndex}
                onSelect={handleDotClick}
              />
            </>
          )}
        </Carousel>
      )}
    </div>
  );
};
