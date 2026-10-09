import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import type { PropertyFeature, ShortlistStatus } from '../../types.ts';
import { postShortlist } from '../../lib/api/properties.ts';
import { Badge } from '@/components/ui/badge.tsx';
import { Card, CardContent } from '@/components/ui/card.tsx';
import { Button } from '@/components/ui/button.tsx';
import { Textarea } from '@/components/ui/textarea.tsx';
import { Skeleton } from '@/components/ui/skeleton.tsx';
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion.tsx';
import { RentSimulator } from './RentSimulator.tsx';
import { ImageCarousel } from './ImageCarousel.tsx';
import { RentPlansTable } from './RentPlansTable.tsx';
import { CampaignCards } from './CampaignCards.tsx';
import { PriceHistorySection, priceDeltaFromHistory } from './PriceHistorySection.tsx';
import { EmptyState } from '@/components/shared/EmptyState.tsx';
import { computeStayEstimate, isListed } from '../../lib/filterLogic.ts';
import {
  roomFloorLabel,
  roomOrientationLabel,
  orientationRotationDeg,
} from '../../lib/room.ts';
import { fmtStatus } from '../../lib/shortlist.ts';
import { formatYen, formatDailyRentDisplay, formatPlanTotalDisplay, formatStayHeader } from '../../lib/format.ts';
import { notify } from '../../lib/notify.ts';
import { mediaImagePairs } from '../../lib/media.ts';
import { useIsMobile } from '../../hooks/useIsMobile.ts';
import { useSwipeDismiss } from '../../hooks/useSwipeDismiss.ts';
import { usePropertyDetail } from '../../hooks/usePropertyDetail.ts';
import {
  FaXmark,
  FaArrowLeftLong,
  FaStar,
  FaBookmark,
  FaEyeSlash,
  FaCircleXmark,
  FaTrain,
  FaArrowUpRightFromSquare,
  FaGlobe,
  FaNoteSticky,
  FaTriangleExclamation,
  FaChartLine,
} from 'react-icons/fa6';
import { Compass } from 'lucide-react';

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
  /** 物件分析モーダルをこの物件で開く */
  onOpenAnalysis?: (propertyId: number) => void;
  /** 「← 建物の部屋一覧」導線(?b= 文脈があるときのみ表示・Phase B2-γ) */
  onBackToBuilding?: () => void;
}

export const DetailPanel: React.FC<DetailPanelProps> = ({
  feature,
  onClose,
  onShortlistUpdate,
  onImageClick,
  checkIn,
  checkOut,
  onDatesChange,
  onDetailPatch,
  onOpenAnalysis,
  onBackToBuilding,
}) => {
  const { detail, loading: detailLoading } = usePropertyDetail(feature?.properties.id);
  /** 価格履歴の品質ガードメタ(詳細APIの price_history_meta。表示中物件のもの) */
  const priceHistoryMeta = detail?.price_history_meta ?? null;
  const [commentDraft, setCommentDraft] = useState('');
  const [commentSaving, setCommentSaving] = useState(false);
  const [commentDirty, setCommentDirty] = useState(false);
  const commentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** 詳細APIで確認した掲載状態（GeoJSONより新しい。null=未取得でGeoJSON値にフォールバック） */
  const unlistedInfo = detail
    ? {
        isActive: detail.is_active ?? true,
        fetchedAt: detail.detail_scraped_at ?? detail.last_seen_at ?? null,
      }
    : null;

  // ── モバイル下スワイプで閉じる ──
  // コンテンツ最上部(scrollTop===0)でのみ発始し、スクロールと両立させる
  const isMobile = useIsMobile();
  const scrollBodyRef = useRef<HTMLDivElement | null>(null);
  /** 退場を始めた物件id。退場中に別物件へ差し替わったら閉じないためのガード */
  const dismissingIdRef = useRef<number | null>(null);
  const swipe = useSwipeDismiss({
    enabled: isMobile,
    direction: 'down',
    scrollContainerRef: scrollBodyRef,
    distanceThresholdPx: 120,
    velocityThresholdPxMs: 0.55,
    onDismiss: onClose,
    onDismissStart: () => {
      dismissingIdRef.current = feature?.properties.id ?? null;
    },
    isDismissValid: () => feature?.properties.id === dismissingIdRef.current,
  });

  // 物件切替時に下書きを親値へリセット
  useEffect(() => {
    if (!feature) return;
    setCommentDraft(feature.properties.shortlist_comment ?? '');
    setCommentDirty(false);
    // Only re-run when selected property changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feature?.properties.id]);

  // 詳細取得結果を親stateへ書き戻す(comment / price_history のマージ)
  useEffect(() => {
    if (!detail || detail.id !== feature?.properties.id) return;
    const status = (detail.shortlist?.status as ShortlistStatus | undefined) ?? undefined;
    const comment = detail.shortlist?.comment ?? null;
    onDetailPatch?.(detail.id, {
      shortlist_comment: comment,
      shortlist_status: status,
      price_history: detail.price_history ?? [],
    });
  }, [detail, onDetailPatch]);

  // Keep draft in sync if parent patches comment while not dirty
  useEffect(() => {
    if (!feature || commentDirty) return;
    setCommentDraft(feature.properties.shortlist_comment ?? '');
  }, [feature?.properties.shortlist_comment, feature?.properties.id, commentDirty]);

  useEffect(() => {
    return () => {
      if (commentTimerRef.current) clearTimeout(commentTimerRef.current);
    };
  }, []);

  /**
   * カルーセル(thumb)/ライトボックス(オリジナル)の URL ペア列。
   * 詳細 API の画像行(media_id 付き)を優先し、未取得・空なら GeoJSON 側の URL 文字列へ
   * フォールバックする(media_id 無し=バックフィル未了・メディア機能無効は従来どおり外部 URL)。
   */
  const galleryImages = useMemo(() => {
    const rows = detail?.images;
    if (rows && rows.length > 0) {
      return mediaImagePairs(
        [...rows].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)),
      );
    }
    const imgs = feature?.properties.images;
    const urls =
      imgs && imgs.length > 0
        ? imgs
        : feature?.properties.thumbnail_url
          ? [feature.properties.thumbnail_url]
          : [];
    return urls.map((url) => ({ thumbUrl: url, fullUrl: url }));
  }, [feature, detail]);

  const images = useMemo(() => galleryImages.map((p) => p.thumbUrl), [galleryImages]);
  const fullImages = useMemo(() => galleryImages.map((p) => p.fullUrl), [galleryImages]);

  const hasActiveCampaign = useMemo(() => {
    // BE campaigns テーブルに is_active 列は無い(常時有効)。掲載中判定は日付で行う
    const cams = feature?.properties.campaigns;
    return !!cams?.length;
  }, [feature]);

  // 掲載終了判定: 詳細APIの結果を優先し、未取得時はGeoJSONの値にフォールバック
  const isUnlisted =
    unlistedInfo != null
      ? !unlistedInfo.isActive
      : feature != null && !isListed(feature.properties);
  const unlistedFetchedAt =
    unlistedInfo?.fetchedAt ?? feature?.properties.last_seen_at ?? null;

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
        await postShortlist(propertyId, effectiveStatus, comment);
        onShortlistUpdate(propertyId, effectiveStatus, comment);
        onDetailPatch?.(propertyId, {
          shortlist_comment: comment,
          shortlist_status: effectiveStatus,
        });
        setCommentDirty(false);
      } catch (err) {
        console.error(err);
        notify('メモの保存に失敗しました。', 'error');
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
  const displayDaily = formatDailyRentDisplay(props.min_daily_rent);
  const displayTotal = formatPlanTotalDisplay(props.min_plan_total);
  const stayHeader = formatStayHeader(est);

  // 所在階・向きは props(RoomView)の整数列から表示正本(lib/room.ts)で導出する。
  // 追加フェッチは行わず、値が無い項目はセルごと非表示にする(設計 §4.2)
  const floorLabel = roomFloorLabel(props);
  const orientationLabel = roomOrientationLabel(props);
  const orientationDeg = orientationRotationDeg(props.orientation_deg);

  // BE 応答の shortlist_status は string。実値は ShortlistStatus 4 値に収まるため scoped cast
  const currentStatus = (props.shortlist_status || 'none') as ShortlistStatus;

  const handleShortlistClick = async (status: 'saved' | 'hide' | 'reject') => {
    const nextStatus = currentStatus === status ? 'none' : status;
    try {
      await postShortlist(props.id, nextStatus, commentDraft || null);
      onShortlistUpdate(props.id, nextStatus, commentDraft || null);
    } catch (err) {
      console.error(err);
      notify('ショートリストの更新に失敗しました。', 'error');
    }
  };

  const coords = feature.geometry?.coordinates;
  const earthUrl = coords
    ? `https://earth.google.com/web/search/${coords[1]},${coords[0]}`
    : '#';
  const isOpen = !!feature;

  return (
    <div
      ref={swipe.targetRef}
      {...swipe.bind}
      className={`
        detail-panel
        ${swipe.isDragging ? 'select-none' : ''}
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
      {/* Close stays fixed on the panel so it remains reachable while scrolling.
          モバイルは下スワイプで閉じるため X はデスクトップのみ */}
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-3 right-3 max-md:hidden bg-black/50 border border-white/20 text-white hover:bg-black/80 hover:scale-110 z-[11]"
        onClick={onClose}
      >
        <FaXmark />
      </Button>

      {/* Body — image + content scroll together */}
      <div ref={scrollBodyRef} className="overflow-y-auto grow min-h-0 overscroll-contain app-scrollbar">
        <div className="flex flex-col gap-4">
          {isUnlisted && (
            <div
              data-testid="unlisted-banner"
              className="flex items-start gap-2 bg-warning/[0.15] text-warning border-b border-warning/30 px-4 py-2.5 text-xs leading-relaxed"
            >
              <FaTriangleExclamation className="mt-0.5 shrink-0" />
              <span>
                この物件は現在サイトに掲載されていません。以下の情報は
                {unlistedFetchedAt
                  ? `最終取得（${unlistedFetchedAt.slice(0, 16).replace('T', ' ')}）`
                  : '最終取得'}
                時点の参考値です。
              </span>
            </div>
          )}
          <ImageCarousel
            images={images}
            fullImages={fullImages}
            propertyId={props.id}
            onImageClick={onImageClick}
          />

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
                  {formatYen(priceDelta.delta)} 前回比
                </Badge>
              )}
              {priceDelta && priceDelta.delta > 0 && (
                <Badge
                  variant="secondary"
                  className="text-xs font-semibold bg-warning/15 text-warning border-warning/40"
                >
                  +{formatYen(priceDelta.delta)} 前回比
                </Badge>
              )}
            </div>

            {onBackToBuilding && (
              <Button
                variant="ghost"
                size="sm"
                className="w-fit px-2 -ml-2 text-text-muted hover:text-text shrink-0"
                onClick={onBackToBuilding}
              >
                <FaArrowLeftLong className="mr-1.5" />
                建物の部屋一覧へ
              </Button>
            )}

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
                    {fmtStatus(currentStatus)}
                  </span>
                </div>
                {/* 所在階・向き: データがある場合のみセルを描画する(§4.2)。 */}
                {floorLabel && (
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-text-muted uppercase">所在階</span>
                    <span className="text-sm font-semibold">{floorLabel}</span>
                  </div>
                )}
                {orientationLabel && (
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-text-muted uppercase">向き</span>
                    <span className="flex items-center gap-1 text-sm font-semibold">
                      {orientationDeg != null && (
                        <Compass
                          className="size-3.5 shrink-0 text-text-muted"
                          style={{ transform: `rotate(${orientationDeg}deg)` }}
                          aria-hidden="true"
                        />
                      )}
                      {orientationLabel}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* 物件分析モーダルへの導線 */}
            {onOpenAnalysis && (
              <Button
                variant="outline"
                size="sm"
                data-testid="open-analysis"
                className="w-full text-xs font-medium text-accent border-accent/40 hover:bg-accent/10 hover:text-accent hover:border-accent/70"
                onClick={() => onOpenAnalysis(props.id)}
              >
                <FaChartLine />
                物件分析
              </Button>
            )}

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
                  <RentPlansTable plans={props.rent_plans} />
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
                      contractFeeYen={props.contract_fee_yen}
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
                    <CampaignCards campaigns={props.campaigns} />
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
                    <EmptyState message="アクセス情報がありません" />
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
                    <EmptyState message="設備情報がありません" />
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
                      <PriceHistorySection history={priceHistory} meta={priceHistoryMeta} />
                    ) : (
                      <EmptyState message="比較できる履歴がまだありません（2回以上の収集が必要）" />
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
