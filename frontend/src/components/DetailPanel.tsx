import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { PropertyDetailResponse, PropertyFeature, ShortlistStatus } from '../types';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableHeader, TableBody, TableHead, TableRow, TableCell } from '@/components/ui/table';
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion';
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselPrevious,
  CarouselNext,
  type CarouselApi,
} from '@/components/ui/carousel';
import { RentSimulator } from './RentSimulator';
import { PriceHistorySection, priceDeltaFromHistory } from './PriceHistorySection';
import { computeStayEstimate } from '../lib/filterLogic';
import {
  FaRegImage,
  FaXmark,
  FaStar,
  FaBookmark,
  FaEyeSlash,
  FaCircleXmark,
  FaRegCalendar,
  FaCircleInfo,
  FaTrain,
  FaArrowUpRightFromSquare,
  FaGlobe,
  FaNoteSticky,
} from 'react-icons/fa6';
import { cn } from '@/lib/utils';

interface DetailPanelProps {
  feature: PropertyFeature | null;
  onClose: () => void;
  onShortlistUpdate: (
    propertyId: number,
    status: ShortlistStatus,
    comment?: string | null,
  ) => void;
  onImageClick: (images: string[], index: number) => void;
  checkIn: string;
  checkOut: string;
  onDatesChange: (checkIn: string, checkOut: string) => void;
  /** Merge lazy detail fields into parent state (comment / price_history). */
  onDetailPatch?: (
    propertyId: number,
    patch: {
      shortlist_comment?: string | null;
      shortlist_status?: ShortlistStatus;
      price_history?: PropertyFeature['properties']['price_history'];
    },
  ) => void;
}

const PLAN_NAME_MAP: Record<string, string> = {
  s_short: 'Sショートプラン',
  short: 'ショートプラン',
  middle: 'ミドルプラン',
  long: 'ロングプラン',
  all: 'すべてのプラン',
  UNKNOWN: '対象プラン不明',
};

export const DetailPanel: React.FC<DetailPanelProps> = ({
  feature,
  onClose,
  onShortlistUpdate,
  onImageClick,
  checkIn,
  checkOut,
  onDatesChange,
  onDetailPatch,
}) => {
  const [slideIndex, setSlideIndex] = useState(0);
  const [imageError, setImageError] = useState<{ [key: number]: boolean }>({});
  const [carouselApi, setCarouselApi] = useState<CarouselApi>();
  const [detailLoading, setDetailLoading] = useState(false);
  const [commentDraft, setCommentDraft] = useState('');
  const [commentSaving, setCommentSaving] = useState(false);
  const [commentDirty, setCommentDirty] = useState(false);
  const commentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFetchedIdRef = useRef<number | null>(null);

  useEffect(() => {
    setSlideIndex(0);
    setImageError({});
  }, [feature?.properties.id]);

  // Lazy-fetch detail (price_history + shortlist.comment)
  useEffect(() => {
    if (!feature) {
      lastFetchedIdRef.current = null;
      return;
    }
    const id = feature.properties.id;
    const alreadyHasHistory =
      Array.isArray(feature.properties.price_history) &&
      feature.properties.price_history.length > 0;
    const alreadyHasComment = feature.properties.shortlist_comment != null;
    // Still refetch when switching ids; skip only if same id already fetched this mount
    if (lastFetchedIdRef.current === id && (alreadyHasHistory || alreadyHasComment)) {
      setCommentDraft(feature.properties.shortlist_comment ?? '');
      setCommentDirty(false);
      return;
    }

    let cancelled = false;
    setDetailLoading(true);
    setCommentDraft(feature.properties.shortlist_comment ?? '');
    setCommentDirty(false);

    (async () => {
      try {
        const res = await fetch(`/api/properties/${id}`);
        if (!res.ok) throw new Error(`detail ${res.status}`);
        const data = (await res.json()) as PropertyDetailResponse;
        if (cancelled) return;
        lastFetchedIdRef.current = id;
        const status = (data.shortlist?.status as ShortlistStatus | undefined) ?? undefined;
        const comment = data.shortlist?.comment ?? null;
        const history = data.price_history ?? [];
        setCommentDraft(comment ?? '');
        onDetailPatch?.(id, {
          shortlist_comment: comment,
          shortlist_status: status,
          price_history: history,
        });
      } catch (e) {
        console.warn('property detail fetch failed', e);
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // Only re-run when selected property changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feature?.properties.id]);

  // Keep draft in sync if parent patches comment while not dirty
  useEffect(() => {
    if (!feature || commentDirty) return;
    setCommentDraft(feature.properties.shortlist_comment ?? '');
  }, [feature?.properties.shortlist_comment, feature?.properties.id, commentDirty]);

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
  }, [feature?.properties.id, carouselApi]);

  useEffect(() => {
    return () => {
      if (commentTimerRef.current) clearTimeout(commentTimerRef.current);
    };
  }, []);

  const hasActiveCampaign = useMemo(() => {
    const cams = feature?.properties.campaigns;
    if (!cams?.length) return false;
    return cams.some((c) => c.is_active !== false);
  }, [feature]);

  const priceHistory = feature?.properties.price_history;
  const hasPriceHistory = Array.isArray(priceHistory) && priceHistory.length >= 2;
  const priceDelta = useMemo(
    () => (priceHistory ? priceDeltaFromHistory(priceHistory) : null),
    [priceHistory],
  );

  const accordionDefaults = useMemo(() => {
    const keys = ['rent', 'address', 'access', 'features'];
    const point =
      typeof feature?.properties.point_text === 'string'
        ? feature.properties.point_text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
        : '';
    if (point) keys.push('intro');
    if (feature?.properties.rent_plans && feature.properties.rent_plans.length > 0) {
      keys.push('simulator');
    }
    // 有効なキャンペーンがある場合のみデフォルト展開
    if (
      feature?.properties.campaigns &&
      feature.properties.campaigns.length > 0 &&
      hasActiveCampaign
    ) {
      keys.push('campaigns');
    }
    if (hasPriceHistory) keys.push('priceHistory');
    keys.push('memo');
    return keys;
  }, [feature, hasActiveCampaign, hasPriceHistory]);

  const handleDotClick = useCallback(
    (index: number) => {
      carouselApi?.scrollTo(index);
    },
    [carouselApi]
  );

  const est = useMemo(() => {
    if (!feature) return null;
    const p = feature.properties;
    if (p.stay_estimate?.ok && p.stay_estimate.stayTotalYen != null) {
      return p.stay_estimate;
    }
    return computeStayEstimate(p, checkIn, checkOut);
  }, [feature, checkIn, checkOut]);

  const saveComment = useCallback(
    async (propertyId: number, status: ShortlistStatus, comment: string) => {
      setCommentSaving(true);
      try {
        // API requires a status; use current or promote to saved when only memo is set
        const effectiveStatus = status === 'none' ? 'saved' : status;
        const res = await fetch(`/api/properties/${propertyId}/shortlist`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: effectiveStatus, comment }),
        });
        if (!res.ok) throw new Error('comment save failed');
        onShortlistUpdate(propertyId, effectiveStatus, comment);
        onDetailPatch?.(propertyId, {
          shortlist_comment: comment,
          shortlist_status: effectiveStatus,
        });
        setCommentDirty(false);
      } catch (err) {
        console.error(err);
        alert('メモの保存に失敗しました。');
      } finally {
        setCommentSaving(false);
      }
    },
    [onShortlistUpdate, onDetailPatch],
  );

  const scheduleCommentSave = useCallback(
    (propertyId: number, status: ShortlistStatus, comment: string) => {
      if (commentTimerRef.current) clearTimeout(commentTimerRef.current);
      commentTimerRef.current = setTimeout(() => {
        void saveComment(propertyId, status, comment);
      }, 600);
    },
    [saveComment],
  );

  if (!feature) return null;

  const props = feature.properties;
  // Normalize intro text (API may include \r\n); empty after trim → hide block
  const pointText =
    typeof props.point_text === 'string'
      ? props.point_text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
      : '';
  const images =
    props.images && props.images.length > 0
      ? props.images
      : props.thumbnail_url
        ? [props.thumbnail_url]
        : [];

  const displayDaily = props.min_daily_rent
    ? `${props.min_daily_rent.toLocaleString()}円/日`
    : '詳細参照';
  const displayTotal = props.min_plan_total
    ? `(プラン総額: ${props.min_plan_total.toLocaleString()}円)`
    : '';
  const stayHeader =
    est?.ok && est.stayTotalYen != null
      ? `${est.stayTotalYen.toLocaleString()}円（${est.stayDays}日）`
      : null;

  const statusMap: Record<string, string> = {
    saved: '保存済み',
    hide: '非表示',
    reject: '見送り',
    none: '未分類',
  };
  const currentStatus = props.shortlist_status || 'none';

  const handleShortlistClick = async (status: 'saved' | 'hide' | 'reject') => {
    const nextStatus = currentStatus === status ? 'none' : status;
    try {
      const res = await fetch(`/api/properties/${props.id}/shortlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: nextStatus,
          comment: commentDraft || null,
        }),
      });
      if (!res.ok) throw new Error('API update failed');
      onShortlistUpdate(props.id, nextStatus, commentDraft || null);
    } catch (err) {
      console.error(err);
      alert('ショートリストの更新に失敗しました。');
    }
  };

  const coords = feature.geometry?.coordinates;
  const earthUrl = coords
    ? `https://earth.google.com/web/search/${coords[1]},${coords[0]}`
    : '#';
  const isOpen = !!feature;

  return (
    <div
      className={`
        detail-panel
        absolute z-[1000] bg-panel backdrop-blur-glass border border-border
        flex flex-col overflow-hidden shadow-[0_10px_40px_rgba(0,0,0,0.6)]
        transition-all duration-400 ease-[cubic-bezier(0.16,1,0.3,1)]
        top-3 right-3 bottom-3 w-[min(420px,calc(100%-1.5rem))] rounded-2xl
        max-md:top-auto max-md:right-0 max-md:left-0 max-md:bottom-0 max-md:w-full
        max-md:max-h-[72dvh] max-md:rounded-t-[20px] max-md:rounded-b-none max-md:z-[2100]
        max-md:shadow-[0_-10px_30px_rgba(0,0,0,0.6)]
        ${
          isOpen
            ? 'opacity-100 translate-x-0 scale-100 pointer-events-auto max-md:translate-y-0'
            : 'opacity-0 translate-x-[40px] scale-95 pointer-events-none max-md:translate-y-full'
        }
      `}
    >
      {/* Close stays fixed on the panel so it remains reachable while scrolling */}
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-3 right-3 bg-black/50 border border-white/20 text-white hover:bg-black/80 hover:scale-110 z-[11]"
        onClick={onClose}
      >
        <FaXmark />
      </Button>

      {/* Body — image + content scroll together */}
      <div className="overflow-y-auto grow min-h-0 app-scrollbar">
        <div className="flex flex-col gap-4">
          {/* Image carousel — scrolls with content; swipe-enabled via embla */}
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
                    <CarouselPrevious
                      variant="ghost"
                      size="icon"
                      className="left-3 top-1/2 -translate-y-1/2 size-9 bg-black/60 border border-white/20 text-white opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto z-10 hover:bg-primary hover:border-accent hover:scale-110 disabled:opacity-0"
                    />
                    <CarouselNext
                      variant="ghost"
                      size="icon"
                      className="right-3 top-1/2 -translate-y-1/2 size-9 bg-black/60 border border-white/20 text-white opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto z-10 hover:bg-primary hover:border-accent hover:scale-110 disabled:opacity-0"
                    />
                    <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1.5 z-10 bg-black/40 py-1 px-2 rounded-[10px]">
                      {images.map((_, index) => (
                        <button
                          key={index}
                          type="button"
                          aria-label={`画像 ${index + 1}`}
                          className={cn(
                            'size-1.5 rounded-full bg-white/40 cursor-pointer transition-all duration-200 border-0 p-0',
                            index === slideIndex && '!bg-accent scale-125'
                          )}
                          onClick={() => handleDotClick(index)}
                        />
                      ))}
                    </div>
                  </>
                )}
              </Carousel>
            )}
          </div>

          <div className="flex flex-col gap-4 px-5 pb-5 max-md:px-4 max-md:pb-4">
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <Badge
                variant="default"
                className="inline-flex items-center gap-1.5 text-xs font-bold py-1 px-2.5 rounded-[20px] w-fit"
              >
                <FaStar />
                <span>{props.total_score ? props.total_score.toFixed(1) : '0.0'}</span>
              </Badge>
              {priceDelta && priceDelta.delta < 0 && (
                <Badge
                  variant="secondary"
                  className="text-xs font-semibold bg-success/20 text-success border-success/40"
                >
                  {priceDelta.delta.toLocaleString()}円 前回比
                </Badge>
              )}
              {priceDelta && priceDelta.delta > 0 && (
                <Badge
                  variant="secondary"
                  className="text-xs font-semibold bg-warning/15 text-warning border-warning/40"
                >
                  +{priceDelta.delta.toLocaleString()}円 前回比
                </Badge>
              )}
            </div>

            <h2 className="text-lg font-bold leading-[1.4] shrink-0">
              {props.title || '無題の物件'}
            </h2>

            <Card size="sm" className="p-0 shrink-0 overflow-visible">
              <CardContent className="grid grid-cols-2 gap-3 p-3">
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-text-muted uppercase">家賃プラン</span>
                  <span className="text-sm font-semibold">
                    {stayHeader ? (
                      <>
                        <span className="text-accent">{stayHeader}</span>
                        <span className="text-text-muted text-sm font-normal ml-1">
                          · {displayDaily}
                        </span>
                      </>
                    ) : (
                      <>
                        {displayDaily} {displayTotal}
                      </>
                    )}
                  </span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-text-muted uppercase">広さ/間取り</span>
                  <span className="text-sm font-semibold">
                    {props.area_m2 ? `${props.area_m2}㎡` : '不明'} / {props.layout || '不明'}
                  </span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-text-muted uppercase">最寄駅</span>
                  <span className="text-sm font-semibold">
                    {props.min_walk_minutes ? `徒歩 ${props.min_walk_minutes}分` : '不明'}
                  </span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-text-muted uppercase">ステータス</span>
                  <span className="text-sm font-semibold">
                    {statusMap[currentStatus] || '未分類'}
                  </span>
                </div>
              </CardContent>
            </Card>

            {/* Shortlist actions (label removed) */}
            <div className="pt-1 shrink-0">
              <div className="flex gap-2">
                {[
                  {
                    status: 'saved',
                    icon: <FaBookmark />,
                    label: '保存',
                    activeClass:
                      'bg-success/[0.15] text-success border-success hover:bg-success/20 hover:text-success',
                  },
                  {
                    status: 'hide',
                    icon: <FaEyeSlash />,
                    label: '非表示',
                    activeClass:
                      'bg-danger/[0.15] text-danger border-danger hover:bg-danger/20 hover:text-danger',
                  },
                  {
                    status: 'reject',
                    icon: <FaCircleXmark />,
                    label: '見送り',
                    activeClass:
                      'bg-warning/[0.15] text-warning border-warning hover:bg-warning/20 hover:text-warning',
                  },
                ].map(({ status, icon, label, activeClass }) => (
                  <Button
                    key={status}
                    variant="outline"
                    size="sm"
                    className={
                      currentStatus === status
                        ? `flex-1 text-xs font-medium ${activeClass}`
                        : 'flex-1 text-xs font-medium text-text-muted hover:text-text hover:bg-white/[0.06]'
                    }
                    onClick={() => handleShortlistClick(status as 'saved' | 'hide' | 'reject')}
                  >
                    {icon}
                    {label}
                  </Button>
                ))}
              </div>
            </div>

            <Accordion
              key={props.id}
              multiple
              defaultValue={accordionDefaults}
              className="w-full border-t border-border/60 shrink-0"
            >
              {pointText ? (
                <AccordionItem value="intro" className="border-border/60">
                  <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                    紹介
                  </AccordionTrigger>
                  <AccordionContent className="pb-3">
                    <div className="rounded-xl border border-primary/30 bg-primary/10 px-3.5 py-3">
                      <p className="m-0 text-sm leading-[1.7] text-[#f1f3f9] whitespace-pre-line break-words">
                        {pointText}
                      </p>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ) : null}

              <AccordionItem value="rent" className="border-border/60">
                <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                  ご利用料金
                </AccordionTrigger>
                <AccordionContent className="pb-3">
                  {props.rent_plans && props.rent_plans.length > 0 ? (
                    <Table className="mt-1 text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
                            プラン
                          </TableHead>
                          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
                            賃料 (日額/総額)
                          </TableHead>
                          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
                            管理費
                          </TableHead>
                          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
                            清掃費
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {props.rent_plans.map((plan, idx) => {
                          let rentText = <span className="text-text-muted italic">取扱無</span>;
                          let mngText = '-';
                          let clnText = '-';

                          if (plan.available) {
                            const effDaily =
                              plan.effective_daily_rent_yen ?? plan.discounted_daily_rent_yen;
                            const effTotal =
                              plan.effective_total_yen ?? plan.discounted_total_yen;
                            const dailyVal = effDaily
                              ? `${effDaily.toLocaleString()}円/日`
                              : '0円/日';
                            const showOriginalStrike =
                              plan.original_daily_rent_yen != null &&
                              effDaily != null &&
                              plan.original_daily_rent_yen !== effDaily;
                            const originalVal = showOriginalStrike ? (
                              <span className="line-through text-text-muted text-xs mr-1">
                                {plan.original_daily_rent_yen!.toLocaleString()}円
                              </span>
                            ) : null;
                            const totalVal =
                              effTotal && plan.total_period_days ? (
                                <span className="text-xs text-text-muted block mt-0.5">
                                  ({plan.total_period_days}日総額:{' '}
                                  {effTotal.toLocaleString()}円)
                                </span>
                              ) : null;
                            const appliedLabel =
                              plan.effective_campaign_label ??
                              (plan.campaign_applied ? plan.campaign_label : null);
                            const campaignVal = appliedLabel ? (
                              <>
                                <br />
                                <span className="inline-block bg-primary/[0.15] text-[#a37aff] py-0.5 px-1.5 rounded text-xs font-semibold mt-0.5 border border-primary/30">
                                  {appliedLabel}
                                </span>
                              </>
                            ) : plan.campaign_expired ? (
                              <>
                                <br />
                                <span className="inline-block bg-white/10 text-text-muted py-0.5 px-1.5 rounded text-xs font-semibold mt-0.5 border border-border/50">
                                  {plan.expired_campaign_label || 'キャンペーン'}（適用終了）
                                </span>
                              </>
                            ) : null;

                            rentText = (
                              <>
                                <span className="text-accent font-bold">
                                  {originalVal}
                                  {dailyVal}
                                </span>
                                {campaignVal}
                                {totalVal}
                              </>
                            );
                            mngText =
                              plan.management_fee_daily_yen !== null
                                ? `${plan.management_fee_daily_yen.toLocaleString()}円/日`
                                : '0円/日';
                            clnText =
                              plan.cleaning_fee_yen !== null
                                ? `${plan.cleaning_fee_yen.toLocaleString()}円`
                                : '0円';
                          }

                          return (
                            <TableRow key={idx}>
                              <TableCell className="font-semibold">{plan.plan_name}</TableCell>
                              <TableCell>{rentText}</TableCell>
                              <TableCell>{mngText}</TableCell>
                              <TableCell>{clnText}</TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  ) : (
                    <p className="text-sm leading-[1.6] text-text-muted italic">
                      料金プラン情報がありません
                    </p>
                  )}
                </AccordionContent>
              </AccordionItem>

              {props.rent_plans && props.rent_plans.length > 0 && (
                <AccordionItem value="simulator" className="border-border/60">
                  <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                    料金シミュレーター
                  </AccordionTrigger>
                  <AccordionContent className="pb-3">
                    <RentSimulator
                      plans={props.rent_plans}
                      campaigns={props.campaigns}
                      propertyId={props.id}
                      hideTitle
                      checkIn={checkIn}
                      checkOut={checkOut}
                      onDatesChange={onDatesChange}
                    />
                  </AccordionContent>
                </AccordionItem>
              )}

              {props.campaigns && props.campaigns.length > 0 && (
                <AccordionItem value="campaigns" className="border-border/60">
                  <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                    <span className="flex flex-1 items-center justify-between gap-2 min-w-0 pr-2">
                      <span>キャンペーン情報</span>
                      {!hasActiveCampaign && (
                        <Badge variant="secondary" className="font-semibold">
                          現在なし
                        </Badge>
                      )}
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="pb-3">
                    <div className="flex flex-col gap-2.5 mt-1">
                      {props.campaigns.map((cam, idx) => {
                        const planName = cam.target_plan_code
                          ? PLAN_NAME_MAP[cam.target_plan_code] || cam.target_plan_code
                          : null;
                        const isActive = cam.is_active !== false;
                        const endUnknown = cam.date_end_unknown === true;

                        return (
                          <Card
                            key={idx}
                            className={`p-3 border transition-all duration-300 ${
                              isActive
                                ? 'border-success/30 bg-success/[0.03] shadow-[0_2px_8px_rgba(34,197,94,0.05)]'
                                : 'border-border/60 bg-white/[0.02] opacity-60'
                            }`}
                          >
                            <div className="flex justify-between items-start gap-2 mb-1.5">
                              <div className="flex flex-wrap gap-1.5 items-center">
                                <Badge
                                  variant={isActive ? 'default' : 'secondary'}
                                  className={`text-xs font-bold px-1.5 py-0.5 ${
                                    isActive ? 'bg-success text-white' : ''
                                  }`}
                                >
                                  {cam.campaign_type || 'キャンペーン'}
                                </Badge>
                                {planName && (
                                  <Badge
                                    variant="outline"
                                    className="text-xs px-1.5 py-0.5 border-[#a37aff]/30 text-[#a37aff]"
                                  >
                                    {planName}
                                  </Badge>
                                )}
                              </div>
                              {!isActive ? (
                                <span className="text-xs text-text-muted font-semibold bg-white/10 px-1 py-0.5 rounded">
                                  期間外・終了
                                </span>
                              ) : endUnknown ? (
                                <span className="text-xs text-text-muted font-semibold bg-white/10 px-1 py-0.5 rounded">
                                  終了日不明・要確認
                                </span>
                              ) : null}
                            </div>
                            <h4 className="text-xs font-bold text-white mb-1">{cam.title}</h4>
                            <p className="text-xs text-text/80 leading-[1.5] mb-2">{cam.content}</p>
                            {(() => {
                              const structBits: string[] = [];
                              if (cam.discount_unit === 'yen' && cam.discount_value != null) {
                                structBits.push(`日額 ${cam.discount_value.toLocaleString()}円引き`);
                              } else if (
                                cam.discount_unit === 'percent' &&
                                cam.discount_value != null
                              ) {
                                structBits.push(`${cam.discount_value}% OFF`);
                              } else if (
                                cam.discount_unit === 'package' &&
                                cam.package_total_benefit_yen != null
                              ) {
                                structBits.push(
                                  `お得額 最大${cam.package_total_benefit_yen.toLocaleString()}円`
                                );
                              } else if (
                                cam.discount_unit === 'pokkiri' &&
                                cam.discount_value != null
                              ) {
                                structBits.push(
                                  `月額 ${cam.discount_value.toLocaleString()}円ポッキリ`
                                );
                              } else if (cam.discount_unit === 'free_first_week') {
                                structBits.push('初週無料');
                              }
                              if (cam.period_max_days != null)
                                structBits.push(`最大${cam.period_max_days}日適用`);
                              if (cam.discount_max_yen != null)
                                structBits.push(`上限${cam.discount_max_yen.toLocaleString()}円`);
                              if (cam.stay_min_days != null || cam.stay_max_days != null) {
                                const a =
                                  cam.stay_min_days != null ? `${cam.stay_min_days}日` : '';
                                const b =
                                  cam.stay_max_days != null ? `${cam.stay_max_days}日` : '';
                                structBits.push(`滞在 ${a}${a && b ? '〜' : ''}${b}`);
                              }
                              return structBits.length > 0 ? (
                                <p className="text-xs text-accent/90 mb-2 m-0 leading-relaxed">
                                  {structBits.join(' · ')}
                                </p>
                              ) : null;
                            })()}

                            <div className="grid grid-cols-1 gap-1 text-xs text-text-muted border-t border-border/40 pt-1.5 mt-1.5">
                              <div className="flex items-start gap-1">
                                <FaRegCalendar className="text-accent mt-[1px]" />
                                <span>
                                  <strong>期間: </strong>
                                  {cam.starts_on && cam.ends_on
                                    ? `${cam.starts_on.replace(/-/g, '/')} 〜 ${cam.ends_on.replace(/-/g, '/')}`
                                    : cam.target_period_text || '期間指定なし'}
                                </span>
                              </div>
                              {cam.target_condition_text && (
                                <div className="flex items-start gap-1">
                                  <FaCircleInfo className="text-accent mt-[1px]" />
                                  <span>
                                    <strong>条件: </strong>
                                    {cam.target_condition_text}
                                  </span>
                                </div>
                              )}
                            </div>
                          </Card>
                        );
                      })}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              )}

              <AccordionItem value="address" className="border-border/60">
                <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                  住所
                </AccordionTrigger>
                <AccordionContent className="pb-3">
                  <p className="text-sm leading-[1.6]">{props.address || ''}</p>
                </AccordionContent>
              </AccordionItem>

              <AccordionItem value="access" className="border-border/60">
                <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                  アクセス
                </AccordionTrigger>
                <AccordionContent className="pb-3">
                  {props.access_summary ? (
                    <ul className="list-none flex flex-col gap-1.5">
                      {props.access_summary.split(', ').map((acc, idx) => (
                        <li key={idx} className="flex gap-2 items-start">
                          <FaTrain className="text-accent mt-[3px] text-xs" />
                          <span>{acc}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-text-muted italic">アクセス情報がありません</p>
                  )}
                </AccordionContent>
              </AccordionItem>

              <AccordionItem value="features" className="border-border/60">
                <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                  主要設備
                </AccordionTrigger>
                <AccordionContent className="pb-3">
                  {props.feature_summary ? (
                    <div className="flex flex-row flex-wrap gap-1.5">
                      {props.feature_summary.split(', ').map((feat, idx) => (
                        <Badge key={idx} variant="outline" className="py-1 px-2.5 text-xs">
                          {feat}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-text-muted italic">設備情報がありません</p>
                  )}
                </AccordionContent>
              </AccordionItem>

              {(hasPriceHistory || detailLoading) && (
                <AccordionItem value="priceHistory" className="border-border/60">
                  <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                    価格履歴
                  </AccordionTrigger>
                  <AccordionContent className="pb-3">
                    {detailLoading && !hasPriceHistory ? (
                      <div className="flex flex-col gap-2">
                        <Skeleton className="h-12 w-full" />
                        <Skeleton className="h-16 w-full" />
                      </div>
                    ) : hasPriceHistory && priceHistory ? (
                      <PriceHistorySection history={priceHistory} />
                    ) : (
                      <p className="text-sm text-text-muted italic">
                        比較できる履歴がまだありません（2回以上の収集が必要）
                      </p>
                    )}
                  </AccordionContent>
                </AccordionItem>
              )}

              <AccordionItem value="memo" className="border-border/60">
                <AccordionTrigger className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted hover:no-underline py-3">
                  <span className="flex items-center gap-2">
                    <FaNoteSticky className="text-accent" />
                    メモ
                    {commentDraft.trim() ? (
                      <Badge variant="secondary" className="text-[10px] font-normal">
                        あり
                      </Badge>
                    ) : null}
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-3">
                  <div className="flex flex-col gap-2">
                    <Textarea
                      value={commentDraft}
                      placeholder="気になった点・比較メモなど（自動保存）"
                      className="min-h-20 bg-white/[0.04] text-sm resize-y"
                      onChange={(e) => {
                        const v = e.target.value;
                        setCommentDraft(v);
                        setCommentDirty(true);
                        scheduleCommentSave(props.id, currentStatus, v);
                      }}
                      onBlur={() => {
                        if (commentDirty) {
                          if (commentTimerRef.current) clearTimeout(commentTimerRef.current);
                          void saveComment(props.id, currentStatus, commentDraft);
                        }
                      }}
                    />
                    <p className="text-[11px] text-text-muted m-0">
                      {commentSaving
                        ? '保存中…'
                        : commentDirty
                          ? '未保存の変更あり'
                          : 'ショートリストに紐づけて保存されます'}
                    </p>
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </div>
        </div>
      </div>

      {/* External Actions — single line labels */}
      <div className="p-4 px-5 border-t border-border bg-black/20 flex gap-3 shrink-0">
        <a
          href={props.detail_url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 min-w-0 py-3 px-2 rounded-lg border-none cursor-pointer font-semibold text-sm flex items-center justify-center gap-1.5 transition-all duration-300 no-underline bg-gradient-to-br from-primary to-[#a37aff] text-white shadow-[0_4px_15px_rgba(133,77,255,0.3)] hover:-translate-y-0.5 hover:shadow-[0_6px_20px_rgba(133,77,255,0.5)] whitespace-nowrap overflow-hidden"
        >
          <FaArrowUpRightFromSquare className="shrink-0" />
          <span className="truncate">公式サイト</span>
        </a>
        <a
          href={earthUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 min-w-0 py-3 px-2 rounded-lg border-none cursor-pointer font-semibold text-sm flex items-center justify-center gap-1.5 transition-all duration-300 no-underline bg-gradient-to-br from-[#34a853] to-[#1a73e8] text-white shadow-[0_4px_15px_rgba(26,115,232,0.3)] hover:-translate-y-0.5 hover:shadow-[0_6px_20px_rgba(26,115,232,0.5)] whitespace-nowrap overflow-hidden"
        >
          <FaGlobe className="shrink-0" />
          <span className="truncate">Google Earth</span>
        </a>
      </div>
    </div>
  );
};
