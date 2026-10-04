"""フロントエンド既定設定 (map layer v2 設計 doc §2)。"""

from fastapi import APIRouter, HTTPException

import api_models

router = APIRouter()


@router.get("/api/fe-settings", response_model=api_models.FeSettingsResponse)
def get_frontend_settings():
    """Return saved frontend default settings (layers / global). Empty when unset."""
    from fe_settings import get_fe_settings

    return get_fe_settings()


@router.post("/api/fe-settings", response_model=api_models.FeSettingsResponse)
def save_frontend_settings(update: dict):
    """Partial-merge save of frontend default settings.

    - `{"layers": {"<id>": {"defaultOpacity": 0.6}}}` → そのキーのみ上書き
    - null 送信でその保存済みキー/レイヤを削除(カタログ既定へ戻す)
    - 返り値は保存後の全体設定

    ボディは意図的に pydantic モデル化しない (update: dict)。null = 保存済み
    キーの削除 (既定へ戻す) という部分マージ契約を保持するためで、値の
    バリデーションは fe_settings 側で行い、違反は 400 で返す。
    """
    from fe_settings import save_fe_settings

    try:
        return save_fe_settings(update)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
