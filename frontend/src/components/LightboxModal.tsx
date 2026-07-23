import React, { useEffect } from 'react';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { Button } from '@/components/ui/button';
import { FaXmark, FaChevronLeft, FaChevronRight } from 'react-icons/fa6';

interface LightboxModalProps {
  isOpen: boolean;
  images: string[];
  currentIndex: number;
  title: string;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}

export const LightboxModal: React.FC<LightboxModalProps> = ({
  isOpen, images, currentIndex, title, onClose, onPrev, onNext,
}) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight') onNext();
      else if (e.key === 'ArrowLeft') onPrev();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, onPrev, onNext]);

  if (!isOpen || images.length === 0) return null;

  return (
    <DialogPrimitive.Root open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-[9998] bg-[rgba(13,14,18,0.95)] backdrop-blur-[12px]"
          onClick={onClose}
        />
        <DialogPrimitive.Popup
          className="fixed inset-0 z-[9999] flex items-center justify-center outline-none"
        >
          <div className="relative max-w-[90%] max-h-[85%] flex flex-col items-center" onClick={(e) => e.stopPropagation()}>
            <Button
              variant="ghost"
              size="icon"
              className="absolute -top-10 right-0 text-white hover:text-accent text-3xl h-auto w-auto"
              onClick={onClose}
            >
              <FaXmark />
            </Button>
            <img className="lightbox-img" src={images[currentIndex]} alt={`${title} - ${currentIndex + 1}`} />
            {images.length > 1 && (
              <>
                <Button
                  variant="ghost"
                  size="icon-lg"
                  className="absolute top-1/2 -translate-y-1/2 max-md:left-2.5 -left-20 bg-[rgba(22,24,33,0.6)] backdrop-blur-glass border border-border text-white w-12 h-12 max-md:w-9 max-md:h-9 rounded-full hover:bg-primary hover:border-accent hover:scale-110 z-[10010]"
                  onClick={onPrev}
                >
                  <FaChevronLeft />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-lg"
                  className="absolute top-1/2 -translate-y-1/2 max-md:right-2.5 -right-20 bg-[rgba(22,24,33,0.6)] backdrop-blur-glass border border-border text-white w-12 h-12 max-md:w-9 max-md:h-9 rounded-full hover:bg-primary hover:border-accent hover:scale-110 z-[10010]"
                  onClick={onNext}
                >
                  <FaChevronRight />
                </Button>
              </>
            )}
            <div className="mt-4 text-text text-sm font-medium text-center [text-shadow:0_2px_4px_rgba(0,0,0,0.8)]">
              {title} ({currentIndex + 1} / {images.length})
            </div>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
};
