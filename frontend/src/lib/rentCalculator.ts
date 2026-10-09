/**
 * BraTTo-style stay cost calculator (Phase 1 + Phase 2).
 *
 * total = (dailyRent + dailyManagement + dailyUtilities) * stayDays
 *         + cleaningFee + contractFee
 * stayDays = inclusive day count (check-out date included)
 * plan is chosen data-driven from duration_min_days/duration_max_days
 * (BE domain/pricing.select_plan_for_stay mirror); plans without duration
 * data fall back to the legacy BraTTo string-band inference.
 *
 * Phase 2:
 * - Prefer effective_daily_rent_yen (backend-resolved; expired → original)
 * - Optionally apply structured campaign fields (period_max, package benefits)
 *
 * 基準日(onDate)セマンティクス(契約):
 * - effective_* フィールドは BE が as-of-today で解決済みのスナップショット値
 * - 滞在試算(calculateRentTotal 系)はチェックイン日基準(キャンペーン適用判定)
 * - 分析面(planCurve / PlanCostTab 等)は as-of-today(getAsOfToday() を明示渡し)
 * - onDate は必須引数。既定値は存在しないので基準日の無自覚な流用はコンパイルエラーになる
 */

import type { Campaign, RentPlan } from '../types';
import { formatYen } from './format';

/**
 * プランコード(wire 語彙)。実語彙は開集合(新サイトでコードが増える)のため
 * string で開放する。表示ラベルの正は BE 解決の plan_label(設計 §3.6)。
 */
export type PlanCode = string;

/**
 * プラン表示ラベル(設計 §3.6)。BE 解決の plan_label(レンジなし)を正とし、
 * 帯レンジは wire の duration_text と合成して既存表示と同等に保つ(2026-10-08 承認)。
 * plan_label が無い(旧キャッシュ・未知コードの生名フォールバック)場合は
 * plan_name 生値をそのまま返す。
 */
export function planDisplayLabel(plan: CalculatorPlan): string {
  const label = plan.plan_label ?? plan.plan_name ?? '';
  const range = plan.duration_text;
  if (!label || !range || label.includes(range)) return label;
  return `${label}（${range}）`;
}

/**
 * GeoJSON / 詳細API の rent_plans 要素 (生成型 RentPlan) から計算に使う
 * フィールドのみを Partial<Pick> 派生した型。BE 契約 (api_models.py) と
 * 名前・型が連動し、フィールドの改名・削除は Pick のキーでコンパイル検知される。
 * 呼び出し側は生成型 RentPlan[] をそのまま渡せる (構造的部分型)。
 */
export type CalculatorPlan = Partial<Pick<
  RentPlan,
  | 'plan_key'
  | 'plan_code'
  /** BE 解決済み表示ラベル(設計 §3.6・レンジなし)。欠損時は plan_name フォールバック */
  | 'plan_label'
  /** BE RentPlan では Optional(nullable)。欠損時の表示は呼び出し側でフォールバック */
  | 'plan_name'
  | 'duration_text'
  /**
   * 滞在帯(日数)。BE price_plans.duration_min_days / duration_max_days のミラー。
   * 両方(またはmin)が有効な物件はデータ駆動でプラン選択する(乖離1修復)。
   */
  | 'duration_min_days'
  | 'duration_max_days'
  | 'available'
  /** utilities_yen の提示単位。"per_month" なら 30 で割って日額化(BE to_per_day 準拠) */
  | 'presentation_unit'
  | 'utilities_yen'
  | 'utilities_included'
  | 'discounted_daily_rent_yen'
  | 'original_daily_rent_yen'
  | 'campaign_label'
  | 'management_fee_daily_yen'
  | 'cleaning_fee_yen'
  /** Backend-resolved effective daily (expired campaigns → original) */
  | 'effective_daily_rent_yen'
  | 'campaign_applied'
  | 'campaign_expired'
  | 'effective_campaign_label'
  | 'expired_campaign_label'
>>;

/**
 * 生成型 Campaign から構造化キャンペーン判定に使うフィールドのみを派生した型。
 * is_active は BE 契約に存在しないため含めない (書くとコンパイルエラーになる)。
 * 有効判定は starts_on / ends_on の日付比較 (isCampaignActiveOnDate) のみで行う。
 * 対象プランキーは target_plan_key が正で、target_plan_code は同値のエイリアスとして
 * 常に併載される (BE campaign_targets_plan_key ミラー)。
 */
export type CalculatorCampaign = Partial<Pick<
  Campaign,
  | 'campaign_type'
  | 'title'
  | 'target_plan_key'
  | 'target_plan_code'
  | 'discount_unit'
  | 'discount_value'
  | 'discount_max_yen'
  | 'period_max_days'
  | 'stay_min_days'
  | 'stay_max_days'
  | 'package_rent_benefit_yen'
  | 'package_cleaning_benefit_yen'
  | 'package_fee_benefit_yen'
  | 'starts_on'
  | 'ends_on'
>>;

export interface CalcInput {
  checkIn: string; // YYYY-MM-DD
  checkOut: string; // YYYY-MM-DD
  plans: CalculatorPlan[];
  campaigns?: CalculatorCampaign[];
  /**
   * 契約事務手数料(円)。物件の contract_fee_yen(BE 解決済み実効値)を渡す。
   * null/undefined は算出不能として総額から除外し、breakdown.contractFee = null
   * + warnings で明示される(BE pricing 準拠。数値への補完は行わない)。
   */
  contractFeeYen?: number | null;
  /** Prefer structured recalculation when campaigns available (default true) */
  useStructuredCampaigns?: boolean;
}

export interface CalcByDaysInput {
  stayDays: number;
  plans: CalculatorPlan[];
  campaigns?: CalculatorCampaign[];
  /**
   * 契約事務手数料(円)。物件の contract_fee_yen(BE 解決済み実効値)を渡す。
   * null/undefined は算出不能として総額から除外し、breakdown.contractFee = null
   * + warnings で明示される。
   */
  contractFeeYen?: number | null;
  useStructuredCampaigns?: boolean;
  /**
   * キャンペーン適用期間判定の基準日(YYYY-MM-DD)。必須。
   * 滞在試算はチェックイン日、分析面は getAsOfToday() を渡すこと。
   */
  onDate: string;
}

export interface CalcBreakdown {
  rentDaily: number;
  managementDaily: number;
  utilitiesDaily: number;
  rentTotal: number;
  managementTotal: number;
  utilitiesTotal: number;
  cleaningFee: number;
  /** null = 取得元サイトの既定が未登録で算出不能(総額から除外) */
  contractFee: number | null;
}

export interface CalcResult {
  ok: true;
  stayDays: number;
  preferredPlanCode: PlanCode;
  selectedPlan: CalculatorPlan;
  selectedPlanCode: PlanCode;
  usedFallback: boolean;
  fallbackNote: string | null;
  breakdown: CalcBreakdown;
  grandTotal: number;
  warnings: string[];
}

export interface CalcError {
  ok: false;
  error: string;
}

export type CalcOutcome = CalcResult | CalcError;

/** Parse YYYY-MM-DD as local calendar date (no TZ shift). */
export function parseIsoDate(iso: string): Date | null {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  if (date.getFullYear() !== y || date.getMonth() !== m - 1 || date.getDate() !== d) {
    return null;
  }
  return date;
}

/** Inclusive stay days: (checkOut - checkIn) + 1. */
export function calcStayDays(checkIn: string, checkOut: string): number | null {
  const start = parseIsoDate(checkIn);
  const end = parseIsoDate(checkOut);
  if (!start || !end) return null;
  const ms = end.getTime() - start.getTime();
  if (ms < 0) return null;
  return Math.floor(ms / 86_400_000) + 1;
}

/** プランの滞在帯(日数)。duration_min_days が無い/不正なプランは null(データ駆動対象外) */
export function planDurationBand(
  plan: CalculatorPlan
): { min: number; max: number | null } | null {
  const dmin = plan.duration_min_days;
  if (dmin == null || !Number.isFinite(dmin)) return null;
  const dmax = plan.duration_max_days;
  if (dmax == null || !Number.isFinite(dmax)) return { min: dmin, max: null };
  return { min: dmin, max: dmax };
}

/**
 * 金額を提示単位から日額へ変換(BE to_per_day ミラー・決定 11 厳格版)。
 * 正式単位は per_day / per_month のみで、per_month は 30 で整数除算(floor)。
 * エイリアス(monthly 等)と未知の単位(per_week 等)は null(算出不能)を返す。
 */
function toPerDay(amount: number, unit: string | null | undefined): number | null {
  const n = Math.trunc(Number(amount));
  if (!Number.isFinite(n)) return null;
  const u = (unit || '').toLowerCase().trim();
  if (u === 'per_day') return n;
  if (u === 'per_month') return Math.floor(n / 30);
  return null;
}

/**
 * 光熱費の日額(BE plan_utilities_per_day ミラー)。
 * utilities_included が明示的に false のときのみ utilities_yen を日額化して返す。
 */
export function planUtilitiesPerDay(plan: CalculatorPlan): number {
  if (plan.utilities_included !== false) return 0;
  const util = plan.utilities_yen;
  if (util == null) return 0;
  return toPerDay(util, plan.presentation_unit) ?? 0;
}

/** Daily rent used for calculation (effective → discounted → original). */
export function planDailyRent(plan: CalculatorPlan): number | null {
  if (plan.effective_daily_rent_yen != null) return plan.effective_daily_rent_yen;
  if (plan.discounted_daily_rent_yen != null) return plan.discounted_daily_rent_yen;
  if (plan.original_daily_rent_yen != null) return plan.original_daily_rent_yen;
  return null;
}

function isPlanUsable(plan: CalculatorPlan): boolean {
  if (!plan.available) return false;
  const daily = planDailyRent(plan);
  if (daily == null) return false;
  if (daily < 0) return false;
  // 算出不能な単位(未知単位の光熱費/管理料)のプランは計算対象から除外する
  // (決定 11・2026-10-09 承認「計算対象除外」— 0 円や過大値に黙認畳み込みしない)
  if (
    plan.utilities_included === false &&
    plan.utilities_yen != null &&
    toPerDay(plan.utilities_yen, plan.presentation_unit) == null
  ) {
    return false;
  }
  // management_fee_daily_yen が null(BE の算出不能)は対象外。未記載は BE が 0 を返す
  if (plan.management_fee_daily_yen === null) return false;
  return true;
}

/**
 * stay日数に対するプランを選択する。
 *
 * 1) duration帯データ(duration_min_days/max_days)がある物件:
 *    BE domain/pricing.select_plan_for_stay のミラー。
 *    - 帯内一致(dmin <= stay <= dmax / max null は上限なし): duration_min_days 昇順で最初の一致
 *    - 該当ゼロ時はより長い帯(min > stay のうち最小min) → 短い帯(min <= stay のうち最大min) → 先頭
 * 2) durationデータが無い物件: 従来の文字列バンド推定(BraTTo固定バンド)にフォールバック。
 *
 * fallbackNote は使用した経路に応じたユーザー向け注記を返す。
 */
export function selectPlanByDays(
  plans: CalculatorPlan[],
  stayDays: number
): {
  preferred: PlanCode;
  selected: CalculatorPlan;
  selectedCode: PlanCode;
  usedFallback: boolean;
  fallbackNote: string | null;
} | null {
  const usable = plans.filter(isPlanUsable);
  if (usable.length === 0) return null;

  // データ駆動経路(BE select_plan_for_stay ミラー)のみ。duration データのない
  // プランは本番に存在しない(BE が duration なしデータを生産不能・実測 0 件)のため、
  // レガシーの文字列バンド推定経路は 2026-10-08 に削除した(設計 §3.6)。
  const banded = usable
    .map((plan) => ({ plan, band: planDurationBand(plan) }))
    .filter((x): x is { plan: CalculatorPlan; band: { min: number; max: number | null } } =>
      x.band != null
    );
  if (banded.length === 0) return null;

  // duration_min_days 昇順
  const ordered = [...banded].sort((a, b) => a.band.min - b.band.min);
  const toResult = (
    c: { plan: CalculatorPlan; band: { min: number; max: number | null } },
    usedFallback: boolean
  ) => {
    const selectedCode = (c.plan.plan_code || c.plan.plan_name || '') as PlanCode;
    const fallbackNote = usedFallback
      ? `この物件に${stayDays}日の滞在に対応する料金プラン帯がないため、` +
        `${planDisplayLabel(c.plan)}の料金で試算しています。`
      : null;
    return {
      preferred: selectedCode,
      selected: c.plan,
      selectedCode,
      usedFallback,
      fallbackNote,
    };
  };

  const exact = ordered.find(
    (c) => stayDays >= c.band.min && (c.band.max == null || stayDays <= c.band.max)
  );
  if (exact) return toResult(exact, false);

  // より長い帯(min > stay のうち最小min)で代替
  const longer = ordered.find((c) => c.band.min > stayDays);
  if (longer) return toResult(longer, true);

  // 短い帯(min <= stay のうち最大min)で代替
  const shorter = [...ordered].reverse().find((c) => c.band.min <= stayDays);
  if (shorter) return toResult(shorter, true);

  return toResult(ordered[0], true);
}

/**
 * キャンペーン対象判定の照合キー。wire の plan_code(= BE plan_key)をそのまま使い、
 * normalizePlanCode による帯の再導出は行わない(BE campaign_targets_plan_key ミラー。
 * 再導出だと plan_key=other 等のプランに対象外キャンペーンが誤適用される)。
 */
function campaignMatchCode(plan: CalculatorPlan): string {
  return (plan.plan_code || '').toLowerCase().trim();
}

function campaignTargetsPlan(cam: CalculatorCampaign, matchCode: string): boolean {
  const target = (cam.target_plan_key || cam.target_plan_code || '').toLowerCase().trim();
  if (!target || target === 'all') return true;
  return target === matchCode;
}

function isCampaignActiveOnDate(cam: CalculatorCampaign, isoDate: string): boolean {
  const d = isoDate;
  if (cam.starts_on && cam.starts_on > d) return false;
  if (cam.ends_on && cam.ends_on < d) return false;
  return true;
}

function filterApplicableCampaigns(
  campaigns: CalculatorCampaign[] | undefined,
  matchCode: string,
  stayDays: number,
  onDate: string
): CalculatorCampaign[] {
  if (!campaigns?.length) return [];
  return campaigns.filter((c) => {
    if (!isCampaignActiveOnDate(c, onDate)) return false;
    if (!campaignTargetsPlan(c, matchCode)) return false;
    if (c.stay_min_days != null && stayDays < c.stay_min_days) return false;
    if (c.stay_max_days != null && stayDays > c.stay_max_days) return false;
    return true;
  });
}

/**
 * Phase 2 structured application: start from original daily, apply unit rules.
 * Falls back to plan effective/discounted when structure is insufficient.
 */
function applyStructuredCampaigns(
  selected: CalculatorPlan,
  stayDays: number,
  onDate: string,
  campaigns: CalculatorCampaign[] | undefined,
  baseContractFee: number | null
): {
  rentDaily: number;
  cleaningFee: number;
  contractFee: number | null;
  notes: string[];
  usedStructure: boolean;
} {
  const original =
    selected.original_daily_rent_yen ??
    selected.effective_daily_rent_yen ??
    selected.discounted_daily_rent_yen ??
    0;
  const fallbackDaily = planDailyRent(selected) ?? original;
  let cleaningFee = selected.cleaning_fee_yen ?? 0;
  let contractFee = baseContractFee;
  const notes: string[] = [];

  const applicable = filterApplicableCampaigns(campaigns, campaignMatchCode(selected), stayDays, onDate);
  if (applicable.length === 0) {
    return {
      rentDaily: fallbackDaily,
      cleaningFee,
      contractFee,
      notes,
      usedStructure: false,
    };
  }

  const yenCams = applicable.filter((c) => c.discount_unit === 'yen' && c.discount_value != null);
  const pctCams = applicable.filter(
    (c) => c.discount_unit === 'percent' && c.discount_value != null
  );
  const pkgCams = applicable.filter((c) => c.discount_unit === 'package');

  let rentDaily = original;
  let usedStructure = false;

  if (yenCams.length > 0) {
    const c = yenCams[0];
    const value = c.discount_value!;
    const periodMax = c.period_max_days;
    const dmax = c.discount_max_yen;
    let applyDays = stayDays;
    if (periodMax != null) applyDays = Math.min(stayDays, periodMax);
    let totalOff = value * applyDays;
    if (dmax != null && totalOff > dmax) totalOff = dmax;
    rentDaily = stayDays > 0 ? Math.max(0, original - Math.floor(totalOff / stayDays)) : original;
    const label = c.campaign_type || c.title || '割引';
    notes.push(`${label}: 日額${formatYen(value)}×${applyDays}日分を反映`);
    usedStructure = true;
  } else if (pctCams.length > 0) {
    const c = pctCams[0];
    const pct = c.discount_value!;
    const periodMax = c.period_max_days;
    const dmax = c.discount_max_yen;
    let applyDays = stayDays;
    if (periodMax != null) applyDays = Math.min(stayDays, periodMax);
    const dailyOff = Math.floor((original * pct) / 100);
    let totalOff = dailyOff * applyDays;
    if (dmax != null && totalOff > dmax) totalOff = dmax;
    rentDaily = stayDays > 0 ? Math.max(0, original - Math.floor(totalOff / stayDays)) : original;
    const label = c.campaign_type || c.title || '割引';
    notes.push(`${label}: ${pct}%OFF×${applyDays}日分を反映`);
    usedStructure = true;
  } else {
    // No yen/percent structure → keep effective snapshot for daily rent
    rentDaily = fallbackDaily;
  }

  for (const c of pkgCams) {
    const label = c.campaign_type || c.title || 'パッケージ';
    const rentBen = c.package_rent_benefit_yen || 0;
    const cleanBen = c.package_cleaning_benefit_yen || 0;
    const feeBen = c.package_fee_benefit_yen || 0;
    if (rentBen && stayDays > 0) {
      rentDaily = Math.max(0, rentDaily - Math.floor(rentBen / stayDays));
    }
    if (cleanBen) cleaningFee = Math.max(0, cleaningFee - cleanBen);
    // 手数料が不明のまま減額すると誤表示になるため、null は null を維持
    if (feeBen && contractFee != null) contractFee = Math.max(0, contractFee - feeBen);
    notes.push(`${label}: パッケージお得を反映`);
    usedStructure = true;
  }

  return { rentDaily, cleaningFee, contractFee, notes, usedStructure };
}

/**
 * チェックイン/チェックアウトの日付から総額を計算(滞在面=チェックイン基準)。
 * 滞在日数の解決のみを行い、実体は calculateRentTotalByDays に委譲する。
 * キャンペーン適用期間の判定基準日はチェックイン日(滞在試算の契約)。
 */
export function calculateRentTotal(input: CalcInput): CalcOutcome {
  const stayDays = calcStayDays(input.checkIn, input.checkOut);
  if (stayDays == null) {
    if (!input.checkIn || !input.checkOut) {
      return { ok: false, error: '入居日と退去日を入力してください。' };
    }
    const start = parseIsoDate(input.checkIn);
    const end = parseIsoDate(input.checkOut);
    if (!start || !end) {
      return { ok: false, error: '日付の形式が正しくありません。' };
    }
    return { ok: false, error: '退去日を入居日以降に設定してください。' };
  }
  return calculateRentTotalByDays({
    stayDays,
    plans: input.plans,
    campaigns: input.campaigns,
    contractFeeYen: input.contractFeeYen,
    useStructuredCampaigns: input.useStructuredCampaigns,
    onDate: input.checkIn,
  });
}

/** 今日のローカル日付(YYYY-MM-DD)。分析面(as-of-today)の基準日取得に使う */
export function getAsOfToday(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * 滞在日数を直接指定する総額計算(本体)。
 * プラン選択・キャンペーン適用・内訳算出を行う。
 * calculateRentTotal は日付から滞在日数を解決して本関数へ委譲する。
 *
 * 基準日契約: onDate は必須。滞在試算はチェックイン日、分析面は getAsOfToday()。
 */
export function calculateRentTotalByDays(input: CalcByDaysInput): CalcOutcome {
  const stayDays = input.stayDays;
  if (!Number.isFinite(stayDays) || stayDays < 1) {
    return { ok: false, error: 'ご利用日数は1日以上である必要があります。' };
  }
  const onDate = input.onDate;

  const selection = selectPlanByDays(input.plans, stayDays);
  if (!selection) {
    return { ok: false, error: '計算可能な料金プランがありません。' };
  }

  const { preferred, selected, selectedCode, usedFallback, fallbackNote } = selection;
  // null = 算出不能(総額から除外し warnings で明示)。数値への補完はしない
  const baseContractFee = input.contractFeeYen ?? null;
  const useStructure = input.useStructuredCampaigns !== false;

  let rentDaily: number;
  let cleaningFee: number;
  let contractFee: number | null;
  const structureNotes: string[] = [];

  if (useStructure && input.campaigns && input.campaigns.length > 0) {
    const applied = applyStructuredCampaigns(
      selected,
      stayDays,
      onDate,
      input.campaigns,
      baseContractFee
    );
    rentDaily = applied.rentDaily;
    cleaningFee = applied.cleaningFee;
    contractFee = applied.contractFee;
    structureNotes.push(...applied.notes);
  } else {
    rentDaily = planDailyRent(selected) ?? 0;
    cleaningFee = selected.cleaning_fee_yen ?? 0;
    contractFee = baseContractFee;
  }

  const managementDaily = selected.management_fee_daily_yen ?? 0;
  const utilitiesDaily = planUtilitiesPerDay(selected);
  const rentTotal = rentDaily * stayDays;
  const managementTotal = managementDaily * stayDays;
  const utilitiesTotal = utilitiesDaily * stayDays;
  const grandTotal =
    rentTotal + managementTotal + utilitiesTotal + cleaningFee + (contractFee ?? 0);

  const warnings: string[] = [];
  if (usedFallback && fallbackNote) {
    warnings.push(fallbackNote);
  }

  if (contractFee == null) {
    warnings.push('契約事務手数料が不明(取得元サイトの既定が未登録)のため、総額から除外しています。');
  }

  if (utilitiesDaily > 0) {
    warnings.push(
      `光熱費（${formatYen(selected.utilities_yen)}/${
        (selected.presentation_unit || 'per_day') === 'per_month' ? '月' : '日'
      }）を日額${formatYen(utilitiesDaily)}で加算しています。`
    );
  }

  if (selected.campaign_expired) {
    warnings.push(
      `期限切れの${selected.expired_campaign_label || 'キャンペーン'}は適用せず、定価ベースで試算しています。`
    );
  } else if (selected.campaign_applied && selected.effective_campaign_label) {
    warnings.push(`有効なキャンペーン（${selected.effective_campaign_label}）を反映しています。`);
  } else if (selected.campaign_label && selected.campaign_applied !== false) {
    warnings.push(`表示中の賃料（${selected.campaign_label}）を使用しています。`);
  }

  for (const n of structureNotes) {
    warnings.push(n);
  }

  return {
    ok: true,
    stayDays,
    preferredPlanCode: preferred,
    selectedPlan: selected,
    selectedPlanCode: selectedCode,
    usedFallback,
    fallbackNote,
    breakdown: {
      rentDaily,
      managementDaily,
      utilitiesDaily,
      rentTotal,
      managementTotal,
      utilitiesTotal,
      cleaningFee,
      contractFee,
    },
    grandTotal,
    warnings,
  };
}
