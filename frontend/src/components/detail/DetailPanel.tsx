import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  PriceHistoryMeta,
  PropertyFeature,
  ShortlistStatus,
} from '../../types.ts';
import { fetchPropertyDetail, postShortlist } from '../../lib/api/properties.ts';
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
import { computeStayEstimate } from '../../lib/filterLogic.ts';
import { notify } from '../../lib/notify.ts';
import {
  FaXmark,
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
  /** Merge lazy detail fields into parent state (comment / price_history / contract fee). */
  onDetailPatch?: (
    propertyId: number,
    patch: {
      shortlist_comment?: string | null;
      shortlist_status?: ShortlistStatus;
      price_history?: PropertyFeature['properties']['price_history'];
      contract_fee_yen?: number | null;
    },
  ) => void;
  /** 物件分析モーダルをこの物件で開く */
  onOpenAnalysis?: (propertyId: number) => void;
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
}) => {
  const [detailLoading, setDetailLoading] = useState(false);
  /** 価格履歴の品質ガードメタ(詳細APIの price_history_meta。表示中物件のもの) */
  const [priceHistoryMeta, setPriceHistoryMeta] = useState<PriceHistoryMeta | null>(null);
  const [commentDraft, setCommentDraft] = useState('');
  const [commentSaving, setCommentSaving] = useState(false);
  const [commentDirty, setCommentDirty] = useState(false);
  const commentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFetchedIdRef = useRef<number | null>(null);
  /** 詳細APIで確認した掲載状態（GeoJSONより新しい。null=未取得でGeoJSON値にフォールバック） */
  const [unlistedInfo, setUnlistedInfo] = useState<{
    isActive: boolean;
    fetchedAt: string | null;
  } | null>(null);

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
    setPriceHistoryMeta(null);
    setCommentDraft(feature.properties.shortlist_comment ?? '');
    setCommentDirty(false);

    (async () => {
      try {
        const data = await fetchPropertyDetail(id);
        if (cancelled) return;
        lastFetchedIdRef.current = id;
        const status = (data.shortlist?.status as ShortlistStatus | undefined) ?? undefined;
        const comment = data.shortlist?.comment ?? null;
        const history = data.price_history ?? [];
        setPriceHistoryMeta(data.price_history_meta ?? null);
        setUnlistedInfo({
          isActive: data.is_active ?? true,
          fetchedAt: data.detail_scraped_at ?? data.last_seen_at ?? null,
        });
        setCommentDraft(comment ?? '');
        onDetailPatch?.(id, {
          shortlist_comment: comment,
          shortlist_status: status,
          price_history: history,
          contract_fee_yen: data.contract_fee_yen ?? null,
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
    return () => {
      if (commentTimerRef.current) clearTimeout(commentTimerRef.current);
    };
  }, []);

  const images = useMemo(() => {
    const imgs = feature?.properties.images;
    if (imgs && imgs.length > 0) return imgs;
    const thumb = feature?.properties.thumbnail_url;
    return thumb ? [thumb] : [];
  }, [feature]);

  const hasActiveCampaign = useMemo(() => {
    // BE campaigns テーブルに is_active 列は無い(常時有効)。掲載中判定は日付で行う
    const cams = feature?.properties.campaigns;
    return !!cams?.length;
  }, [feature]);

  // 掲載終了判定: 詳細APIの結果を優先し、未取得時はGeoJSONの値にフォールバック
  const isUnlisted =
    unlistedInfo != null ? !unlistedInfo.isActive : feature?.properties.is_active === false;
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
          <ImageCarousel images={images} propertyId={props.id} onImageClick={onImageClick} />

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
                      <PriceHistorySection history={priceHistory} meta={priceHistoryMeta} />
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
