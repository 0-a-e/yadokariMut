import React from 'react';
import { getAsOfToday } from '../../lib/rentCalculator.ts';

/**
 * 今日基準(as-of-today)で計算した分析面の表示に付ける共通注記。
 * 滞在シミュレーション面(チェックイン基準)と区別するため、
 * 基準日を明示して「この数値は取得時点の解決値」という契約を見せる。
 */
export const AsOfNote: React.FC = () => (
  <p className="text-[11px] text-text-muted m-0 leading-relaxed">
    as of {getAsOfToday()} 計算（キャンペーン適用は今日基準）
  </p>
);
