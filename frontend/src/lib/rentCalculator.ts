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

export const CONTRACT_FEE_YEN = 5500;

/** Plan bands ordered short → long (BraTTo official thresholds). */
export const PLAN_BAND_ORDER = ['s_short', 'short', 'middle', 'long'] as const;
export type PlanCode = (typeof PLAN_BAND_ORDER)[number];

export const PLAN_LABELS: Record<PlanCode, string> = {
  s_short: 'Sショート（1ヶ月未満）',
  short: 'ショート（1〜3ヶ月）',
  middle: 'ミドル（3〜6ヶ月）',
  long: 'ロング（6ヶ月以上）',
};

export interface CalculatorPlan {
  plan_key?: string | null;
  plan_code?: string | null;
  /** BE RentPlan では Optional(nullable)。欠損時の表示は呼び出し側でフォールバック */
  plan_name?: string | null;
  duration_text?: string | null;
  /**
   * 滞在帯(日数)。BE price_plans.duration_min_days / duration_max_days のミラー。
   * 両方(またはmin)が有効な物件はデータ駆動でプラン選択する(乖離1修復)。
   */
  duration_min_days?: number | null;
  duration_max_days?: number | null;
  available: boolean;
  /** utilities_yen の提示単位。"per_month" なら 30 で割って日額化(BE to_per_day 準拠) */
  presentation_unit?: string | null;
  utilities_yen?: number | null;
  utilities_included?: boolean | null;
  discounted_daily_rent_yen?: number | null;
  original_daily_rent_yen?: number | null;
  campaign_label?: string | null;
  management_fee_daily_yen?: number | null;
  cleaning_fee_yen?: number | null;
  /** Backend-resolved effective daily (expired campaigns → original) */
  effective_daily_rent_yen?: number | null;
  campaign_applied?: boolean;
  campaign_expired?: boolean;
  effective_campaign_label?: string | null;
  expired_campaign_label?: string | null;
}

export interface CalculatorCampaign {
  campaign_type?: string | null;
  title?: string | null;
  is_active?: boolean;
  target_plan_code?: string | null;
  discount_unit?: string | null;
  discount_value?: number | null;
  discount_max_yen?: number | null;
  period_max_days?: number | null;
  stay_min_days?: number | null;
  stay_max_days?: number | null;
  package_rent_benefit_yen?: number | null;
  package_cleaning_benefit_yen?: number | null;
  package_fee_benefit_yen?: number | null;
  starts_on?: string | null;
  ends_on?: string | null;
}

export interface CalcInput {
  checkIn: string; // YYYY-MM-DD
  checkOut: string; // YYYY-MM-DD
  plans: CalculatorPlan[];
  campaigns?: CalculatorCampaign[];
  /**
   * 契約事務手数料(円)。物件の contract_fee_yen(詳細APIのみ)を渡す。
   * null/undefined は既定値 CONTRACT_FEE_YEN にフォールバック(BE pricing 準拠)。
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
   * 契約事務手数料(円)。物件の contract_fee_yen(詳細APIのみ)を渡す。
   * null/undefined は既定値 CONTRACT_FEE_YEN にフォールバック(BE pricing 準拠)。
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
  contractFee: number;
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

/**
 * Official band: <30 s_short, <91 short, <181 middle, else long.
 * レガシーフォールバック用(BraTTo固定バンド)。durationデータがある物件では使わない。
 */
export function preferredPlanCodeForDays(stayDays: number): PlanCode {
  if (stayDays < 30) return 's_short';
  if (stayDays < 91) return 'short';
  if (stayDays < 181) return 'middle';
  return 'long';
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
 * 金額を提示単位から日額へ変換(BE to_per_day ミラー)。
 * per_month は 30 で整数除算(floor)、未知の単位は per_day 扱い。
 */
function toPerDay(amount: number, unit: string | null | undefined): number | null {
  const n = Math.trunc(Number(amount));
  if (!Number.isFinite(n)) return null;
  const u = (unit || 'per_day').toLowerCase().trim();
  if (u === 'per_month' || u === 'monthly' || u === 'month') {
    return Math.floor(n / 30);
  }
  return n;
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

function normalizePlanCode(plan: CalculatorPlan): PlanCode | null {
  const raw = (plan.plan_code || '').toLowerCase().trim();
  if ((PLAN_BAND_ORDER as readonly string[]).includes(raw)) {
    return raw as PlanCode;
  }
  // Fallback from plan_name when plan_code is missing
  const name = (plan.plan_name || '').toLowerCase();
  if (name.includes('sショート') || name.includes('s-short') || name.includes('1ヶ月未満')) {
    return 's_short';
  }
  if (name.includes('ショート') || name.includes('1ヶ月') || name.includes('1～3') || name.includes('1~3')) {
    // avoid matching s_short again
    if (!name.includes('sショート') && !name.includes('s-short')) return 'short';
  }
  if (name.includes('ミドル') || name.includes('3ヶ月') || name.includes('3～6') || name.includes('3~6')) {
    return 'middle';
  }
  if (name.includes('ロング') || name.includes('6ヶ月')) {
    return 'long';
  }
  return null;
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
  return true;
}

/**
 * プラン表示用コード。normalizePlanCode で解決できない帯(独自 plan_key 等)は
 * plan_code をそのまま表示キーとして使う(PLAN_LABELS 未登録コードは
 * 呼び出し側が plan_name にフォールバックする)。
 */
function displayPlanCode(plan: CalculatorPlan): PlanCode {
  return normalizePlanCode(plan) ?? ((plan.plan_code || plan.plan_name) as PlanCode);
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

  const banded = usable
    .map((plan) => ({ plan, band: planDurationBand(plan) }))
    .filter((x): x is { plan: CalculatorPlan; band: { min: number; max: number | null } } =>
      x.band != null
    );

  if (banded.length > 0) {
    // データ駆動経路(BE select_plan_for_stay ミラー): duration_min_days 昇順
    const ordered = [...banded].sort((a, b) => a.band.min - b.band.min);
    const toResult = (
      c: { plan: CalculatorPlan; band: { min: number; max: number | null } },
      usedFallback: boolean
    ) => {
      const selectedCode = displayPlanCode(c.plan);
      const preferred = usedFallback ? preferredPlanCodeForDays(stayDays) : selectedCode;
      const fallbackNote = usedFallback
        ? `この物件に${stayDays}日の滞在に対応する料金プラン帯がないため、` +
          `${c.plan.plan_name ?? ''}の料金で試算しています。`
        : null;
      return {
        preferred,
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

  // レガシー経路: plan_code/plan_name 文字列から BraTTo 固定バンドを推定
  const preferred = preferredPlanCodeForDays(stayDays);
  const byCode = new Map<PlanCode, CalculatorPlan>();
  for (const plan of usable) {
    const code = normalizePlanCode(plan);
    if (code != null && !byCode.has(code)) byCode.set(code, plan);
  }

  const prefIdx = PLAN_BAND_ORDER.indexOf(preferred);
  // Longer bands first (official-style upgrade), then shorter
  const searchOrder: PlanCode[] = [
    ...PLAN_BAND_ORDER.slice(prefIdx),
    ...PLAN_BAND_ORDER.slice(0, prefIdx).reverse(),
  ];

  for (const code of searchOrder) {
    const plan = byCode.get(code);
    if (plan) {
      return {
        preferred,
        selected: plan,
        selectedCode: code,
        usedFallback: code !== preferred,
        fallbackNote:
          code !== preferred
            ? `この物件に${PLAN_LABELS[preferred]}がないため、` +
              `${PLAN_LABELS[code]}の料金で試算しています。`
            : null,
      };
    }
  }
  return null;
}

function campaignTargetsPlan(cam: CalculatorCampaign, planCode: PlanCode): boolean {
  const target = (cam.target_plan_code || '').toLowerCase().trim();
  if (!target || target === 'all') return true;
  return target === planCode;
}

function isCampaignActiveOnDate(cam: CalculatorCampaign, isoDate: string): boolean {
  if (cam.is_active === false) return false;
  const d = isoDate;
  if (cam.starts_on && cam.starts_on > d) return false;
  if (cam.ends_on && cam.ends_on < d) return false;
  return true;
}

function filterApplicableCampaigns(
  campaigns: CalculatorCampaign[] | undefined,
  planCode: PlanCode,
  stayDays: number,
  onDate: string
): CalculatorCampaign[] {
  if (!campaigns?.length) return [];
  return campaigns.filter((c) => {
    if (!isCampaignActiveOnDate(c, onDate)) return false;
    if (!campaignTargetsPlan(c, planCode)) return false;
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
  planCode: PlanCode,
  stayDays: number,
  onDate: string,
  campaigns: CalculatorCampaign[] | undefined,
  baseContractFee: number
): {
  rentDaily: number;
  cleaningFee: number;
  contractFee: number;
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

  const applicable = filterApplicableCampaigns(campaigns, planCode, stayDays, onDate);
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
    notes.push(`${label}: 日額${value.toLocaleString()}円×${applyDays}日分を反映`);
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
    if (feeBen) contractFee = Math.max(0, contractFee - feeBen);
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
  const baseContractFee = input.contractFeeYen ?? CONTRACT_FEE_YEN;
  const useStructure = input.useStructuredCampaigns !== false;

  let rentDaily: number;
  let cleaningFee: number;
  let contractFee: number;
  const structureNotes: string[] = [];

  if (useStructure && input.campaigns && input.campaigns.length > 0) {
    const applied = applyStructuredCampaigns(
      selected,
      selectedCode,
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
    rentTotal + managementTotal + utilitiesTotal + cleaningFee + contractFee;

  const warnings: string[] = [];
  if (usedFallback && fallbackNote) {
    warnings.push(fallbackNote);
  }

  if (utilitiesDaily > 0) {
    warnings.push(
      `光熱費（${selected.utilities_yen?.toLocaleString()}円/${
        (selected.presentation_unit || 'per_day') === 'per_month' ? '月' : '日'
      }）を日額${utilitiesDaily.toLocaleString()}円で加算しています。`
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
