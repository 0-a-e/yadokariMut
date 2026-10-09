/**
 * 物件分析「料金プラン」タブ用の滞在日数×実質1日単価カーブ構築。
 *
 * 1〜90日は1日刻み、91日以降は7日刻みで掃引し、プランバンド境界日は必ず
 * サンプルに含める(duration帯データがある物件は帯境界、無い物件は BraTTo 固定バンド境界)。
 * 各日数で calculateRentTotalByDays を呼び、その日数で適用されたプランの
 * 実質1日単価(=総額/日数)のみを values に記録する(チャートの Line 分離用)。
 */
import {
  calculateRentTotalByDays,
  getAsOfToday,
  planDailyRent,
  planDurationBand,
  type CalculatorCampaign,
  type CalculatorPlan,
  planDisplayLabel,
} from '../rentCalculator.ts';

export interface PlanCurveRow {
  days: number;
  /** 各プランの実質1日単価(その日数で適用されるプランのみ値が入り、他は null) */
  values: Record<string, number | null>;
  /** その日数で適用されたプラン */
  planCode: string;
  /** 総額 */
  total: number;
  /** 実質1日単価 = total / days(四捨五入) */
  perDay: number;
}

export interface PlanCurveResult {
  rows: PlanCurveRow[];
  /** 実質1日単価が最安になる日数(最小の perDay を持つ row) */
  cheapest: PlanCurveRow | null;
  /** 破損値(rent<=0)等で除外したプランの plan_code 一覧 */
  excludedPlans: string[];
  /** plan_code → 表示ラベル(plan_label+帯レンジ合成・設計 §3.6)。凡例表示用 */
  labels: Record<string, string>;
}

export interface PlanDiscountInfo {
  planCode: string;
  planName: string;
  originalDaily: number;
  currentDaily: number;
  /** 割引率(小数1桁の %)。original/current のいずれかが不正値なら null */
  discountPct: number | null;
}

/** 計算に使える正の日額を持つか。0円・負値はキャンペーン二重差引等の破損データ */
function isRentPositive(plan: CalculatorPlan): boolean {
  const rent = plan.discounted_daily_rent_yen ?? plan.original_daily_rent_yen;
  return rent != null && rent > 0 && (planDailyRent(plan) ?? 0) > 0;
}

/** 破損プラン(rent<=0)を除外し、計算対象プランと除外コード一覧を返す */
export function filterBrokenPlans(plans: CalculatorPlan[]): {
  usable: CalculatorPlan[];
  excluded: string[];
} {
  const usable: CalculatorPlan[] = [];
  const excluded: string[] = [];
  for (const p of plans) {
    if (isRentPositive(p)) {
      usable.push(p);
    } else {
      excluded.push(p.plan_code || p.plan_name || '');
    }
  }
  return { usable, excluded };
}

/**
 * 滞在日数 1〜maxDays の実質1日単価カーブを構築する(分析面=as-of-today基準)。
 * キャンペーンの適用判定基準日は getAsOfToday() を明示的に渡す。
 */
export function buildPlanCurve(
  plans: CalculatorPlan[],
  campaigns?: CalculatorCampaign[],
  maxDays = 730,
  contractFeeYen?: number | null,
): PlanCurveResult {
  const { usable, excluded } = filterBrokenPlans(plans);
  const onDate = getAsOfToday();

  const limit = Math.max(1, Math.floor(maxDays));
  const daySet = new Set<number>();
  // 1..90 は全日数、以降は7日刻み
  for (let d = 1; d <= Math.min(90, limit); d++) daySet.add(d);
  for (let d = 91; d <= limit; d += 7) daySet.add(d);
  // プランバンド境界(適用プランが切り替わる日)は刻みに関係なく必ず含める。
  // duration帯データがある物件は帯の端(min / max+1)、無い物件は BraTTo 固定バンド境界。
  const bandEdges = new Set<number>();
  let hasBandData = false;
  for (const p of usable) {
    const band = planDurationBand(p);
    if (!band) continue;
    hasBandData = true;
    bandEdges.add(band.min);
    if (band.max != null) bandEdges.add(band.max + 1);
  }
  if (hasBandData) {
    for (const d of bandEdges) {
      if (d >= 2 && d <= limit) daySet.add(d);
    }
  } else {
    // duration データ欠損経路(本番では到達不能・BE が生産不能)。等間隔ステップで置く
    const step = Math.max(1, Math.floor(limit / 60));
    for (let d = 2; d <= limit; d += step) daySet.add(d);
  }
  const dayList = [...daySet].sort((a, b) => a - b);

  const drafts: Omit<PlanCurveRow, 'values'>[] = [];
  for (const days of dayList) {
    const outcome = calculateRentTotalByDays({
      stayDays: days,
      plans: usable,
      campaigns,
      onDate,
      contractFeeYen,
    });
    if (!outcome.ok) continue;
    drafts.push({
      days,
      planCode: outcome.selectedPlanCode,
      total: outcome.grandTotal,
      perDay: Math.round(outcome.grandTotal / days),
    });
  }

  // チャートでプラン別 Line に分けるため、values は全出現プランコードのキーを持ち、
  // その日数で適用されたプランのみ実質1日単価(他は null)
  const codes = [...new Set(drafts.map((d) => d.planCode))];
  const rows: PlanCurveRow[] = drafts.map((d) => {
    const values: Record<string, number | null> = {};
    for (const c of codes) values[c] = c === d.planCode ? d.perDay : null;
    return { ...d, values };
  });

  let cheapest: PlanCurveRow | null = null;
  for (const row of rows) {
    if (!cheapest || row.perDay < cheapest.perDay) cheapest = row;
  }

  // code → 表示ラベル(plan_label ベース・未知コードは生名フォールバック)
  const labels: Record<string, string> = {};
  for (const p of usable) {
    const code = p.plan_code || p.plan_name || '';
    if (code && !labels[code]) labels[code] = planDisplayLabel(p) || code;
  }
  return { rows, cheapest, excludedPlans: excluded, labels };
}

/** 各プランの定価→現在値の日額から割引率(小数1桁の %)を算出する */
export function planDiscounts(plans: CalculatorPlan[]): PlanDiscountInfo[] {
  return plans.map((p) => {
    const original = p.original_daily_rent_yen;
    const current = p.discounted_daily_rent_yen;
    return {
      planCode: p.plan_code || p.plan_name || '',
      planName: planDisplayLabel(p) || '',
      originalDaily: original ?? 0,
      currentDaily: current ?? 0,
      discountPct:
        typeof original === 'number' &&
        original > 0 &&
        typeof current === 'number' &&
        current > 0
          ? Math.round((1 - current / original) * 1000) / 10
          : null,
    };
  });
}
