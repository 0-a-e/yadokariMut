"""価格変動推移 (FE frontend/src/lib/api/analysis.ts 対応で properties から分離)。"""

from typing import Optional

from fastapi import APIRouter, Query

import api_models
from store.api_queries import get_price_trend

router = APIRouter()


@router.get(
    "/api/analysis/price-trend",
    response_model=api_models.PriceTrendResponse,
)
def get_price_trend_api(
    days: int = Query(90, ge=7, le=730, description="集計期間(日数)。今日から遡る"),
    prefecture_name: Optional[str] = Query(None, description="この都道府県の物件のみで集計する"),
):
    """日次の価格変動推移(中央値/平均/掲載物件数/値下げ・値上げ件数)を返す.

    全プロバイダ分を一括返却し、FE 側で「すべて/プロバイダ別」を切替える。
    prefecture_name 指定時は物件分析モーダルの「同都道府県の市場中央値」用に
    その県の物件のみで集計する(空文字列は未指定扱いで全県)。
    """
    return get_price_trend(days=days, prefecture_name=prefecture_name)
