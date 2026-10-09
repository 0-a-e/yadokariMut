"""領域別ルータ (FE frontend/src/lib/api/ の粒度と 1:1 対応)。

- agent.py       CopilotKit / AG-UI 直結
- chat.py        チャットスレッド (チェックポイント履歴)
- fe_settings.py フロント既定設定
- geojson.py     マップビューア / GeoJSON (一括 + NDJSON ストリーム)
- buildings_geojson.py 建物単位 GeoJSON (一括 + NDJSON ストリーム・Phase B1)
- properties.py  物件詳細 / ショートリスト
- analysis.py    価格推移
- export.py      KML エクスポート
- admin.py       admin (status / sources / scrape / scrape-settings / geocode)
- rotation.py    県ローテーション (status / run / settings)

登録順の制約 (OpenAPI byte 同値) については web/app.py の create_app() 参照。
"""
