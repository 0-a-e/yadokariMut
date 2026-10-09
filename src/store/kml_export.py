"""KML ドキュメント生成 (Google Earth 用エクスポート).

HTTP (/api/export/kml) と MCP/CLI (export_kml) の共通実装。
入力は search_properties / get_properties_by_ids の返す物件辞書の
シーケンスで、緯度経度のない物件は Placemark から除外する。
"""

from __future__ import annotations

from datetime import datetime
from html import escape as _html_escape
from typing import Any, Iterable
from xml.sax.saxutils import escape as _xml_escape

# KML の色は #AABBGGRR (alpha, blue, green, red の順)。
# Web で馴染みのある #RRGGBB との混同を防ぐため、ここで一元的に定義する。
#   stActive = #50a050 (緑) / stSaved = #2e7dd1 (青) / stInactive = #999999 (灰)
#   stBuildingSaved = #8e6fd1 (紫・建物saved の準ずる色・部屋自身の saved が優先)
_STYLE_DEFS = """    <Style id="stActive">
      <IconStyle>
        <color>ff50a050</color>
        <scale>1.0</scale>
        <Icon>
          <href>https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
    </Style>
    <Style id="stSaved">
      <IconStyle>
        <color>ffd17d2e</color>
        <scale>1.15</scale>
        <Icon>
          <href>https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
    </Style>
    <Style id="stBuildingSaved">
      <IconStyle>
        <color>ffd16f8e</color>
        <scale>1.05</scale>
        <Icon>
          <href>https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
    </Style>
    <Style id="stInactive">
      <IconStyle>
        <color>ff999999</color>
        <scale>0.8</scale>
        <Icon>
          <href>https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
    </Style>
"""


def _esc(value: Any) -> str:
    """XML テキストノード・属性値用のエスケープ."""
    return _xml_escape("" if value is None else str(value))


def _h(value: Any) -> str:
    """description CDATA 内の HTML へ値を補間する際のエスケープ."""
    return _html_escape("" if value is None else str(value), quote=True)


def _yen(value: Any) -> str:
    try:
        return f"{int(value):,}円"
    except (TypeError, ValueError):
        return "—"


def _style_id(prop: dict[str, Any]) -> str:
    if prop.get("is_active") is False:
        return "stInactive"
    if prop.get("shortlist_status") == "saved":
        return "stSaved"
    if prop.get("building_shortlist_status") == "saved":
        return "stBuildingSaved"
    return "stActive"


def _placemark_name(prop: dict[str, Any]) -> str:
    """一覧で眺めやすいよう先頭に最安日額を接頭する."""
    title = _esc(prop.get("title") or "(無題)")
    daily = prop.get("min_daily_rent")
    if daily:
        try:
            return f"{int(daily):,}円 | {title}"
        except (TypeError, ValueError):
            pass
    return title


def _plans_html(prop: dict[str, Any]) -> str:
    rows = []
    for plan in prop.get("rent_plans") or []:
        if not plan.get("available"):
            continue
        daily = plan.get("effective_daily_rent_yen")
        if daily is None:
            daily = plan.get("discounted_daily_rent_yen")
        if daily is None:
            continue
        try:
            daily_txt = f"{int(daily):,}円/日"
            total = plan.get("effective_total_yen") or plan.get("discounted_total_yen")
            total_txt = f"{int(total):,}円(30日)" if total else "—"
        except (TypeError, ValueError):
            continue
        label = plan.get("effective_campaign_label") or (
            plan.get("campaign_label") if plan.get("campaign_applied") else None
        )
        if label:
            daily_txt += f" ({label})"
        # プラン列の表示の正は plan_label (辞書解決・レンジ無し)。
        # plan_name は未知コードフォールバック (標準変換を通らない辞書向けの保険)
        rows.append(
            f"<tr><td>{_h(plan.get('plan_label') or plan.get('plan_name'))}</td>"
            f"<td>{_h(daily_txt)}</td><td>{_h(total_txt)}</td></tr>"
        )
    if not rows:
        return ""
    return (
        '<table border="1" style="border-collapse:collapse;font-size:11px;margin-top:8px;">'
        '<tr style="background:#f2f2f2;"><th>プラン</th><th>賃料</th><th>30日総額</th></tr>'
        + "".join(rows)
        + "</table>"
    )


def _description_html(prop: dict[str, Any]) -> str:
    parts: list[str] = [f"<h3>{_h(prop.get('title'))}</h3>"]
    if prop.get("is_active") is False:
        _ls = prop.get("last_seen_at")
        last_seen = (_ls.isoformat()[:10] if hasattr(_ls, "isoformat") else str(_ls or ""))[:10]
        last_txt = f" (最終確認: {_h(last_seen)})" if last_seen else ""
        parts.append(
            f'<p style="color:#b00;"><b>掲載終了</b> — 価格等は最終取得時点の参考値{last_txt}</p>'
        )
    daily = prop.get("min_daily_rent")
    if daily:
        # 最安プランの表示も plan_label (辞書解決) を正とする
        plan_txt = _h(prop.get("min_plan_label") or prop.get("min_plan_name") or "")
        total = prop.get("min_plan_total")
        total_txt = f" / 30日 {int(total):,}円" if total else ""
        parts.append(f"<p><b>最安賃料:</b> {_yen(daily)}/日 {plan_txt}{_h(total_txt)}</p>")
    layout_area = " / ".join(
        x
        for x in [
            str(prop.get("layout") or ""),
            f"{prop.get('area_m2')}㎡" if prop.get("area_m2") else "",
        ]
        if x
    )
    if layout_area:
        parts.append(f"<p><b>間取り/面積:</b> {_h(layout_area)}</p>")
    addr = " ".join(x for x in [prop.get("prefecture_name"), prop.get("address")] if x)
    if addr:
        parts.append(f"<p><b>住所:</b> {_h(addr)}</p>")
    access = prop.get("access_summary")
    if access:
        access_str = ", ".join(access) if isinstance(access, list) else str(access)
        parts.append(f"<p><b>アクセス:</b> {_h(access_str)}</p>")
    site = prop.get("source_display_name") or prop.get("source_site")
    if site:
        parts.append(f"<p><b>掲載サイト:</b> {_h(site)}</p>")
    thumb = prop.get("thumbnail_url")
    if thumb:
        parts.append(f'<img src="{_h(thumb)}" style="max-width:240px;"/>')
    plans = _plans_html(prop)
    if plans:
        parts.append(plans)
    url = prop.get("detail_url")
    if url:
        parts.append(f'<p><a href="{_h(url)}" target="_blank">詳細ページを開く</a></p>')
    return "".join(parts)


def _cdata(html_text: str) -> str:
    """CDATA はネストできないため、終端シーケンスを分割して無効化する."""
    return f"<![CDATA[{html_text.replace(']]>', ']]]]><![CDATA[>')}]]>"


def _placemark(prop: dict[str, Any]) -> str | None:
    lat, lng = prop.get("lat"), prop.get("lng")
    if lat is None or lng is None:
        return None

    ext_rows = [
        ("id", prop.get("id")),
        ("room_id", prop.get("source_property_id") or prop.get("external_id")),
        ("source_site", prop.get("source_site")),
        ("prefecture_name", prop.get("prefecture_name")),
        ("layout", prop.get("layout")),
        ("area_m2", prop.get("area_m2")),
        ("min_daily_rent", prop.get("min_daily_rent")),
        ("min_plan_total", prop.get("min_plan_total")),
        ("min_plan_name", prop.get("min_plan_name")),
        ("min_plan_label", prop.get("min_plan_label")),
        ("min_walk_minutes", prop.get("min_walk_minutes")),
        ("shortlist_status", prop.get("shortlist_status") or "none"),
        ("is_active", prop.get("is_active")),
        ("last_seen_at", prop.get("last_seen_at")),
        ("detail_url", prop.get("detail_url")),
    ]
    # 建物文脈 (建物単位集約モデル・設計 §6.3)。入力 dict に建物列があれば
    # 加算的に載せる。未割当 (None) は Data 行自体を省略する (Placemark は
    # 部屋単位のまま維持)。
    for _bkey in ("building_id", "building_name"):
        _bval = prop.get(_bkey)
        if _bval is not None:
            ext_rows.append((_bkey, _bval))
    ext = "".join(
        f'<Data name="{_esc(name)}"><value>{_esc(value)}</value></Data>'
        for name, value in ext_rows
    )
    return (
        "    <Placemark>\n"
        f"      <name>{_placemark_name(prop)}</name>\n"
        f"      <styleUrl>#{_style_id(prop)}</styleUrl>\n"
        f"      <description>{_cdata(_description_html(prop))}</description>\n"
        f"      <ExtendedData>{ext}</ExtendedData>\n"
        f"      <Point><coordinates>{lng},{lat},0</coordinates></Point>\n"
        "    </Placemark>\n"
    )


def build_kml_document(
    properties: Iterable[dict[str, Any]], doc_name: str | None = None
) -> str:
    """物件辞書のシーケンスを KML ドキュメント文字列へ変換する."""
    if doc_name is None:
        doc_name = f"YadokariMut エクスポート ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    placemarks = []
    for prop in properties:
        pm = _placemark(prop)
        if pm is not None:
            placemarks.append(pm)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document>\n"
        f"    <name>{_esc(doc_name)}</name>\n"
        f"{_STYLE_DEFS}"
        f"{''.join(placemarks)}"
        "  </Document>\n"
        "</kml>\n"
    )
