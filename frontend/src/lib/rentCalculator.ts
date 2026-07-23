/**
 * BraTTo-style stay cost calculator (Phase 1 + Phase 2).
 *
 * total = (dailyRent + dailyManagement) * stayDays + cleaningFee + contractFee
 * stayDays = inclusive day count (check-out date included)
 * plan band is chosen from stay length, with fallback to next available plan
 *
 * Phase 2:
 * - Prefer effective_daily_rent_yen (backend-resolved; expired → original)
 * - Optionally apply structured campaign fields (period_max, package benefits)
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
  plan_code?: string | null;
  plan_name: string;
  available: boolean;
  discounted_daily_rent_yen: number | null;
  original_daily_rent_yen?: number | null;
  campaign_label?: string | null;
  management_fee_daily_yen: number | null;
  cleaning_fee_yen: number | null;
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
  contractFeeYen?: number;
  /** Prefer structured recalculation when campaigns available (default true) */
  useStructuredCampaigns?: boolean;
}

export interface CalcBreakdown {
  rentDaily: number;
  managementDaily: number;
  rentTotal: number;
  managementTotal: number;
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
 */
export function preferredPlanCodeForDays(stayDays: number): PlanCode {
  if (stayDays < 30) return 's_short';
  if (stayDays < 91) return 'short';
  if (stayDays < 181) return 'middle';
  return 'long';
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
 * Prefer the band for stayDays; if unavailable, try longer bands then shorter.
 */
export function selectPlanByDays(
  plans: CalculatorPlan[],
  stayDays: number
): {
  preferred: PlanCode;
  selected: CalculatorPlan;
  selectedCode: PlanCode;
  usedFallback: boolean;
} | null {
  const preferred = preferredPlanCodeForDays(stayDays);
  const usable = plans
    .filter(isPlanUsable)
    .map((p) => ({ plan: p, code: normalizePlanCode(p) }))
    .filter((x): x is { plan: CalculatorPlan; code: PlanCode } => x.code != null);

  if (usable.length === 0) return null;

  const byCode = new Map<PlanCode, CalculatorPlan>();
  for (const { plan, code } of usable) {
    if (!byCode.has(code)) byCode.set(code, plan);
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
  checkIn: string
): CalculatorCampaign[] {
  if (!campaigns?.length) return [];
  return campaigns.filter((c) => {
    if (!isCampaignActiveOnDate(c, checkIn)) return false;
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
  checkIn: string,
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

  const applicable = filterApplicableCampaigns(campaigns, planCode, stayDays, checkIn);
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
  if (stayDays < 1) {
    return { ok: false, error: 'ご利用日数は1日以上である必要があります。' };
  }

  const selection = selectPlanByDays(input.plans, stayDays);
  if (!selection) {
    return { ok: false, error: '計算可能な料金プランがありません。' };
  }

  const { preferred, selected, selectedCode, usedFallback } = selection;
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
      input.checkIn,
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
  const rentTotal = rentDaily * stayDays;
  const managementTotal = managementDaily * stayDays;
  const grandTotal = rentTotal + managementTotal + cleaningFee + contractFee;

  const warnings: string[] = [];
  let fallbackNote: string | null = null;
  if (usedFallback) {
    fallbackNote =
      `この物件に${PLAN_LABELS[preferred]}がないため、` +
      `${PLAN_LABELS[selectedCode]}の料金で試算しています。`;
    warnings.push(fallbackNote);
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
      rentTotal,
      managementTotal,
      cleaningFee,
      contractFee,
    },
    grandTotal,
    warnings,
  };
}

/** Default date range: check-in = first day of next month, check-out = one month later. */
export function defaultDateRange(today: Date = new Date()): { checkIn: string; checkOut: string } {
  const pad = (n: number) => String(n).padStart(2, '0');
  const toIso = (d: Date) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  // 来月1日 〜 その1ヶ月後（翌々月1日）
  const checkIn = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  const checkOut = new Date(today.getFullYear(), today.getMonth() + 2, 1);
  return { checkIn: toIso(checkIn), checkOut: toIso(checkOut) };
}

const RENT_SIM_DATE_STORAGE_KEY = 'yadokari:rent-sim:dates';
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE_RE.test(value)) return false;
  return parseIsoDate(value) != null;
}

/** Load simulator period from localStorage, or fall back to defaultDateRange(). */
export function loadStoredDateRange(today: Date = new Date()): {
  checkIn: string;
  checkOut: string;
} {
  try {
    if (typeof localStorage === 'undefined') return defaultDateRange(today);
    const raw = localStorage.getItem(RENT_SIM_DATE_STORAGE_KEY);
    if (!raw) return defaultDateRange(today);
    const parsed = JSON.parse(raw) as { checkIn?: unknown; checkOut?: unknown };
    const checkIn = typeof parsed.checkIn === 'string' ? parsed.checkIn : '';
    const checkOut = typeof parsed.checkOut === 'string' ? parsed.checkOut : '';
    if (!isValidIsoDate(checkIn) || !isValidIsoDate(checkOut)) {
      return defaultDateRange(today);
    }
    const start = parseIsoDate(checkIn)!;
    const end = parseIsoDate(checkOut)!;
    if (end.getTime() < start.getTime()) return defaultDateRange(today);
    return { checkIn, checkOut };
  } catch {
    return defaultDateRange(today);
  }
}

/** Persist simulator period for the next visit. */
export function saveStoredDateRange(checkIn: string, checkOut: string): void {
  try {
    if (typeof localStorage === 'undefined') return;
    if (!isValidIsoDate(checkIn) || !isValidIsoDate(checkOut)) return;
    localStorage.setItem(
      RENT_SIM_DATE_STORAGE_KEY,
      JSON.stringify({ checkIn, checkOut })
    );
  } catch {
    // quota / private mode — ignore
  }
}
