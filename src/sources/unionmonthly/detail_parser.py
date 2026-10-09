"""Union Monthly detail page → PropertyDraft."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from domain.models import (
    Campaign,
    PricePlan,
    PropertyAccess,
    PropertyDraft,
    PropertyFeature,
    PropertyImage,
    PropertyLink,
)
from domain.pricing import MONTH_DAYS
from sources.base import ListCard
from sources.parsing import (
    parse_floor_text,
    parse_japanese_era,
    parse_money,
    parse_orientation_text,
    split_access,
)
from sources.unionmonthly.plans import (
    UNION_DURATION_BANDS,
    UNION_PLAN_CODE_MAP,
    parse_union_duration_text,
)
from store.pref_master import PREF_DISPLAY_NAMES

BASE = "https://www.unionmonthly.jp"
PARSER_VERSION = "unionmonthly-detail-1.3"

# 住所走査用の県名リスト。正本 (store.pref_master) から派生させる。
# gunma/gumma 別名で値が重複するため set 化し、長い県名 (4文字) を先に照合する。
_PREF_NAMES = sorted(set(PREF_DISPLAY_NAMES.values()), key=len, reverse=True)

# 全物件共通で掲載されるバナー（物件固有のキャンペーンではないため登録対象外）
SITE_WIDE_CAMPAIGN_TITLES = {"嬉しい3大特典キャンペーン"}

# スタッフのおすすめコメント(comment-box)のブロック見出し行。実データ 5,315 件全走査の
# 先頭マーカー分布(■路線情報 4,789 / ＜路線情報(最寄駅→主要駅)＞ 442 / ＜物件の特徴＞ 21 /
# ＜○○駅おすすめコメント＞ 等・2026-10-09)に基づく。この行以前は
# 「○○県○○市の○○駅の…」「ユニオンマンスリー○○です」のボイラープレート 2 行のみ。
_POINT_MARKER_RE = re.compile(r"^(?:■|＜|【).*(?:コメント|特徴|情報)")


def _parse_point_text(soup: BeautifulSoup) -> str | None:
    """スタッフのおすすめコメントを point_text 向けテキストへ整形する。

    section.comment が無ければ None。comment-box 本文を行正規化したのち、
    最初のブロック見出し行以前のボイラープレートのみ落とし、以降
    (■路線情報・■周辺情報・自由文コメント)は原文どおり保持する。
    見出しが 1 行も無い変種は全文フォールバック(情報欠落を避ける)。
    """
    section = soup.select_one("section.comment")
    if section is None:
        return None
    box = section.select_one("div.comment-box") or section
    lines = [ln.strip() for ln in box.get_text("\n").split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    if not text:
        return None
    all_lines = text.split("\n")
    for i, ln in enumerate(all_lines):
        if _POINT_MARKER_RE.match(ln):
            return "\n".join(all_lines[i:]).strip() or None
    return text


def parse_detail_html(
    html: str,
    *,
    card: ListCard | None = None,
    base_url: str = BASE,
    detail_url: str | None = None,
) -> PropertyDraft:
    soup = BeautifulSoup(html, "html.parser")
    card = card or ListCard(external_id="", detail_url=detail_url or "")

    external_id = _extract_id(soup, card, detail_url or card.detail_url)
    title = _text(soup.select_one("h1")) or card.title
    specs = _parse_info_table(soup)
    address = _clean_address(specs.get("住所") or card.address)
    layout, area = _parse_layout_area(
        specs.get("間取り/広さ") or specs.get("間取り") or _text(soup.select_one(".reserve_floor"))
    )
    built_year, built_month, year_text = _parse_built(specs.get("築年") or specs.get("築年月"))
    structure = specs.get("構造")
    capacity = specs.get("入居可能人数")
    # 所在階は floors_text に原文を保存し、整数階数は parse_floor_text で導出する
    # (SSOT: sources.parsing.parse_floor_text / docs/floor-number-ssot-plan.md §3.4)。
    shozokai_text = specs.get("所在階")
    floor_spec = parse_floor_text(shozokai_text)
    # 向きは原文+角度+取得経路の 3 列。角度が取れたときのみ source を設定し
    # 取れない場合は 3 列とも NULL (docs/orientation-model-plan.md §6.1)。
    muki_raw = specs.get("向き")
    orientation = parse_orientation_text(muki_raw)
    orientation_text = muki_raw if orientation.deg is not None else None
    orientation_source = "spec_parse" if orientation.deg is not None else None
    lat, lng = _parse_geo(html, soup)
    pref_name, municipality = _split_pref_muni(address)
    prefecture_slug = card.prefecture_slug or _pref_slug_from_url(detail_url or card.detail_url)

    accesses = _parse_accesses(soup, html)
    features = _parse_features(soup)
    plans = _parse_price_plans(soup)
    campaigns = _parse_campaigns(soup)
    images = _parse_images(soup, base_url=base_url)
    links = _parse_links(soup, base_url=base_url)
    point_text = _parse_point_text(soup)

    min_stay = None
    if "最低契約" in soup.get_text():
        m = re.search(r"最低契約日数[^\d]*(\d+)\s*([かヶヵカ]月|日)", soup.get_text())
        if m:
            n = int(m.group(1))
            min_stay = n * MONTH_DAYS if "月" in m.group(2) else n

    return PropertyDraft(
        source_site="unionmonthly",
        external_id=external_id,
        entity_type="room",
        title=title,
        detail_url=detail_url or card.detail_url,
        prefecture_slug=prefecture_slug,
        prefecture_name=card.prefecture_name or pref_name,
        municipality=municipality,
        address=address,
        lat=lat,
        lng=lng,
        geocode_source="detail_map" if lat is not None else None,
        geocode_confidence=0.9 if lat is not None else None,
        layout=layout,
        area_m2=area,
        built_year=built_year,
        built_month=built_month,
        construction_year_text=year_text,
        capacity_text=capacity,
        structure=structure,
        floors_text=shozokai_text,
        floor_number=floor_spec.floor_min,
        floor_number_max=floor_spec.floor_max,
        building_floors=floor_spec.building_floors,
        orientation_text=orientation_text,
        orientation_deg=orientation.deg,
        orientation_source=orientation_source,
        min_stay_days=min_stay,
        point_text=point_text,
        detail_scraped_at=datetime.now().isoformat(),
        accesses=accesses,
        images=images,
        links=links,
        features=features,
        price_plans=plans,
        campaigns=campaigns,
        parser_version=PARSER_VERSION,
    )


def _extract_id(soup: BeautifulSoup, card: ListCard, url: str | None) -> str:
    entry = soup.select_one("section.entry[data-troom_id], section.entry")
    if entry and entry.get("data-troom_id"):
        return str(entry["data-troom_id"])
    if card.external_id:
        return str(card.external_id)
    if url:
        m = re.search(r"/(\d+)/?(?:\?|$)", url)
        if m:
            return m.group(1)
    return "unknown"


def _parse_info_table(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    for table in soup.select("table.infoTbl_table, table.u-tbl02"):
        for tr in table.select("tr"):
            ths = tr.find_all("th")
            tds = tr.find_all("td")
            if len(ths) == 1 and len(tds) == 1:
                k = ths[0].get_text(strip=True)
                v = tds[0].get_text(" ", strip=True)
                if k and k not in specs:
                    specs[k] = v
            elif len(ths) == 2 and len(tds) == 2:
                for th, td in zip(ths, tds):
                    k = th.get_text(strip=True)
                    v = td.get_text(" ", strip=True)
                    if k and k not in specs:
                        specs[k] = v
    return specs


def _clean_address(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"\s*google map.*$", "", text, flags=re.I).strip()
    t = re.sub(r"\s+", " ", t)
    return t or None


def _parse_layout_area(text: str | None) -> tuple[Optional[str], Optional[float]]:
    if not text:
        return None, None
    t = text.replace("㎡", "m²").replace("m2", "m²")
    layout = None
    area = None
    m = re.search(r"([0-9]+[A-Z]*[RLDK]+(?:[A-Z]*)?)", t, re.I)
    if m:
        layout = m.group(1).upper().replace("Ｌ", "L").replace("Ｄ", "D").replace("Ｋ", "K")
        # normalize fullwidth digits already half
    m2 = re.search(r"([\d.]+)\s*m", t, re.I)
    if m2:
        try:
            area = float(m2.group(1))
        except ValueError:
            pass
    if not layout:
        layout = t.split("/")[0].strip() or None
    return layout, area


def _parse_built(text: str | None) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """築年テキストを (西暦年, 月, 原文) へ解釈する。

    共通層 sources.parsing.parse_japanese_era 経由で和暦
    (昭和/平成/令和) にも対応。旧実装は西暦のみで、和暦表記の物件で
    built_year が欠落していた。
    """
    if not text:
        return None, None, None
    year, month = parse_japanese_era(text)
    return year, month, text.strip()


def _parse_geo(html: str, soup: BeautifulSoup) -> tuple[Optional[float], Optional[float]]:
    for pat in [
        r"[?&]q=([0-9.]+),([0-9.]+)",
        r"@([0-9.]+),([0-9.]+)",
        r"ll=([0-9.]+),([0-9.]+)",
    ]:
        m = re.search(pat, html)
        if m:
            try:
                lat, lng = float(m.group(1)), float(m.group(2))
                if 20 < lat < 50 and 120 < lng < 150:
                    return lat, lng
            except ValueError:
                pass
    return None, None


def _split_pref_muni(address: str | None) -> tuple[Optional[str], Optional[str]]:
    if not address:
        return None, None
    for p in _PREF_NAMES:
        if address.startswith(p):
            rest = address[len(p) :].strip()
            m = re.match(r"(.+?[市区町村])", rest)
            muni = m.group(1) if m else None
            return p, muni
    return None, None


def _pref_slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"unionmonthly\.jp/([a-z]+)/", url)
    return m.group(1) if m else None


def _parse_accesses(soup: BeautifulSoup, html: str) -> list[PropertyAccess]:
    accesses: list[PropertyAccess] = []
    seen: set[str] = set()
    candidates: list[str] = []
    for li in soup.select("ul.gArticle_infoList li"):
        if li.select_one("i.icon-marker"):
            continue
        # <br> 区切りで複駅記載の場合があるため行ごとに候補化
        for t in (part.strip() for part in li.get_text("\n").split("\n")):
            if t and ("徒歩" in t or "駅" in t):
                candidates.append(t)
    meta = soup.select_one('meta[name="description"]')
    if meta and meta.get("content"):
        m = re.search(r"最寄り駅[：:]\s*([^。]+)", meta["content"])
        if m:
            candidates.append(m.group(1).strip())
    # table 交通/最寄駅 rows
    for th in soup.find_all("th"):
        th_txt = th.get_text(strip=True)
        if "交通" in th_txt or "最寄" in th_txt:
            td = th.find_parent("tr").find("td") if th.find_parent("tr") else None
            if td:
                for part in re.split(r"[\n/|]", td.get_text("\n")):
                    part = part.strip()
                    if part and ("駅" in part or "徒歩" in part):
                        candidates.append(part)

    for i, raw in enumerate(candidates):
        if raw in seen:
            continue
        seen.add(raw)
        line, station, walk = split_access(raw)
        accesses.append(
            PropertyAccess(
                line_name=line,
                station_name=station,
                walk_minutes=walk,
                raw_text=raw,
                sort_order=i,
            )
        )
    return accesses


def _parse_features(soup: BeautifulSoup) -> list[PropertyFeature]:
    """生値 + 辞書ルックアップした category のみを書く(設計 §4.2・決定 1/20)。

    サイト見出し(cat_map)と list_tag 出自マーカーは廃止。facility_list の
    <li class="-active"> が物件事実のマーカー(非 active は未達成のグレーアウト
    表示)のため active のみ、entry_tag / tagList はサイト運営バッジとして採る。
    """
    from domain.feature_categories import lookup_feature_category

    def _append(features: list[PropertyFeature], name: str) -> None:
        cat = lookup_feature_category(name)
        features.append(
            PropertyFeature(feature_name=name, category=cat.code if cat else None)
        )

    features: list[PropertyFeature] = []
    for table in soup.select("table.facility_table"):
        for tr in table.select("tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if not th or not td:
                continue
            parts = re.split(r"[、,，]", td.get_text("、", strip=True))
            for p in parts:
                name = p.strip()
                if name:
                    _append(features, name)
    chips = list(soup.select(".entry_tag li, .tagList li"))
    chips += [
        li for li in soup.select(".facility_list li")
        if "-active" in (li.get("class") or [])
    ]
    for el in chips:
        name = el.get_text(strip=True)
        if name:
            _append(features, name)
    # dedupe(feature_name 単位 — UNIQUE(property_id, feature_name) と同じ鍵)
    seen: set[str] = set()
    out: list[PropertyFeature] = []
    for f in features:
        if f.feature_name in seen:
            continue
        seen.add(f.feature_name)
        out.append(f)
    return out


def _parse_price_plans(soup: BeautifulSoup) -> list[PricePlan]:
    tabs = [li.get_text(strip=True) for li in soup.select(".outline_plan_tab_item")]
    panels = soup.select(".outline_plan_tab_panel")
    plans: list[PricePlan] = []

    for i, panel in enumerate(panels):
        tab_name = tabs[i] if i < len(tabs) else f"plan_{i}"
        plan_key = UNION_PLAN_CODE_MAP.get(tab_name, re.sub(r"\W+", "_", tab_name).lower() or f"plan_{i}")

        rent_orig = rent_cur = mgmt = clean_orig = clean_cur = None
        duration_text = None

        for block in panel.select(".outline_plan_tab_block"):
            h4 = block.select_one("h4")
            ttl = h4.get_text(strip=True) if h4 else ""
            if "内訳" in ttl:
                # 賃料 original from .normal, current from campaign column
                for dl in block.select("dl"):
                    dt = dl.select_one("dt")
                    label = dt.get_text(strip=True) if dt else ""
                    bs = [parse_money(b.get_text()) for b in dl.select("b")]
                    bs = [x for x in bs if x is not None]
                    if "賃料" in label:
                        if bs:
                            rent_orig = bs[0]
                        # campaign amount often in sibling right box
                    elif "共益" in label:
                        if bs:
                            mgmt = bs[0]
                # right column campaign rents without dt
                right_bs = []
                for box in block.select(".outline_price_box_right b, .campaign_price_list b"):
                    v = parse_money(box.get_text())
                    if v is not None:
                        right_bs.append(v)
                left_rent = None
                for dl in block.select(".outline_price_box_left dl, .normal_price_list"):
                    dt = dl.select_one("dt")
                    if dt and "賃料" in dt.get_text():
                        left_rent = parse_money(dl.get_text())
                # Better pass: walk price boxes
                rent_orig, rent_cur, mgmt = _parse_uchiwake(block, rent_orig, rent_cur, mgmt)
            elif "清掃" in ttl:
                nums = [parse_money(b.get_text()) for b in block.select("b")]
                nums = [n for n in nums if n is not None]
                if len(nums) >= 2:
                    clean_orig, clean_cur = nums[0], nums[1]
                elif len(nums) == 1:
                    clean_cur = nums[0]
            elif re.search(r"\d+\s*ヶ?月|ヶ月|カ月", ttl) or "未満" in ttl or "以上" in ttl:
                duration_text = ttl
                # headline totals (rent+mgmt)
                normal = block.select_one(".normal_price_list b")
                camp = block.select_one(".campaign_price_list b")
                # keep as raw only; prefer 内訳

        # Fallback: if only totals known
        if rent_cur is None and rent_orig is None:
            # try campaign/normal totals minus mgmt
            for block in panel.select(".outline_plan_tab_block"):
                h4 = block.select_one("h4")
                ttl = h4.get_text(strip=True) if h4 else ""
                if "内訳" in ttl or "清掃" in ttl:
                    continue
                n = block.select_one(".normal_price_list b")
                c = block.select_one(".campaign_price_list b")
                if n:
                    rent_orig = parse_money(n.get_text())
                if c:
                    rent_cur = parse_money(c.get_text())
            # these are totals including mgmt — subtract if mgmt known later

        # Re-parse 内訳 carefully once more with dedicated helper on full panel
        u_rent_o, u_rent_c, u_mgmt, u_clean_o, u_clean_c = _parse_panel_breakdown(panel)
        if u_rent_o is not None:
            rent_orig = u_rent_o
        if u_rent_c is not None:
            rent_cur = u_rent_c
        if u_mgmt is not None:
            mgmt = u_mgmt
        if u_clean_o is not None:
            clean_orig = u_clean_o
        if u_clean_c is not None:
            clean_cur = u_clean_c

        if rent_cur is None:
            rent_cur = rent_orig
        if rent_orig is None and rent_cur is not None:
            rent_orig = rent_cur

        cleaning = clean_cur if clean_cur is not None else clean_orig
        campaign_label = "キャンペーン料金" if (
            rent_orig is not None and rent_cur is not None and rent_cur != rent_orig
        ) else None

        if rent_cur is None and rent_orig is None:
            continue

        # 期間帯域: duration_text からの解析値を優先し、取れない側のみ静的バンドで補完
        band = UNION_DURATION_BANDS.get(plan_key, (1, None))
        parsed_min, parsed_max = parse_union_duration_text(duration_text)
        dmin = parsed_min if parsed_min is not None else band[0]
        dmax = parsed_max if parsed_max is not None else band[1]

        # 単位: パネル内に「円/日」表記があれば日額（空白を除去して比較）
        panel_text = re.sub(r"\s+", "", panel.get_text())
        if "円/日" in panel_text:
            unit = "per_day"
        elif plan_key in ("s_short", "semi_short"):
            # 判定不能テキストへのフォールバック（これらの帯域は日額課金）
            unit = "per_day"
        else:
            unit = "per_month"

        plans.append(
            PricePlan(
                plan_key=plan_key,
                plan_name=tab_name if duration_text is None else f"{tab_name}（{duration_text}）",
                duration_min_days=dmin,
                duration_max_days=dmax,
                available=True,
                presentation_unit=unit,
                rent_original_yen=rent_orig,
                rent_current_yen=rent_cur,
                management_yen=mgmt,
                utilities_yen=None,
                utilities_included=True,  # 水道光熱費不要
                cleaning_yen=cleaning,
                campaign_label=campaign_label,
                raw_text=duration_text,
            )
        )
    return plans


def _parse_uchiwake(block, rent_orig, rent_cur, mgmt):
    return _parse_panel_breakdown(block)[:3]


def _parse_panel_breakdown(panel) -> tuple:
    """Return rent_orig, rent_cur, mgmt, clean_orig, clean_cur from panel 内訳/清掃."""
    rent_orig = rent_cur = mgmt = clean_orig = clean_cur = None
    for block in panel.select(".outline_plan_tab_block"):
        h4 = block.select_one("h4")
        ttl = h4.get_text(strip=True) if h4 else ""
        if "内訳" in ttl:
            # Iterate price rows: each outline_price_box is a fee line
            for box in block.select(".outline_price_box"):
                left = box.select_one(".outline_price_box_left")
                right = box.select_one(".outline_price_box_right")
                label = ""
                if left:
                    dt = left.select_one("dt")
                    label = dt.get_text(strip=True) if dt else left.get_text(" ", strip=True)
                left_val = parse_money(left.get_text()) if left else None
                right_val = parse_money(right.get_text()) if right else None
                if "賃料" in label:
                    rent_orig = left_val if left_val is not None else rent_orig
                    rent_cur = right_val if right_val is not None else rent_cur
                elif "共益" in label:
                    # often same both sides
                    mgmt = right_val if right_val is not None else left_val
        if "清掃" in ttl:
            left = block.select_one(".outline_price_box_left") or block.select_one(".normal_price_list")
            right = block.select_one(".outline_price_box_right") or block.select_one(".campaign_price_list")
            nums = [parse_money(b.get_text()) for b in block.select("b")]
            nums = [n for n in nums if n is not None]
            if len(nums) >= 2:
                clean_orig, clean_cur = nums[0], nums[1]
            elif len(nums) == 1:
                clean_cur = nums[0]
    return rent_orig, rent_cur, mgmt, clean_orig, clean_cur


def _parse_campaigns(soup: BeautifulSoup) -> list[Campaign]:
    campaigns: list[Campaign] = []
    # Headline campaign block
    for sub in soup.select(".campaign_Subtitle, .campaign h3"):
        title = sub.get_text(strip=True)
        if not title or title in ("対象条件", "対象期間"):
            continue
        if title in SITE_WIDE_CAMPAIGN_TITLES:
            continue
        parent = sub.find_parent(["section", "div"]) or sub.parent
        content = parent.get_text("\n", strip=True)[:2000] if parent else title
        campaigns.append(
            Campaign(
                campaign_type=title[:80],
                title=title,
                content=content,
                target_plan_key="all",
            )
        )
        break
    # Ensure at least a marker if campaign prices exist
    if not campaigns and soup.select_one(".campaign_price_list"):
        campaigns.append(
            Campaign(
                campaign_type="キャンペーン料金",
                title="キャンペーン料金",
                content="詳細ページのキャンペーン料金を適用",
                target_plan_key="all",
            )
        )
    return campaigns


def _parse_images(soup: BeautifulSoup, *, base_url: str) -> list[PropertyImage]:
    images: list[PropertyImage] = []
    seen: set[str] = set()
    for i, img in enumerate(soup.select(".vis_image img, .vis_thumbSlide_image img, div.gArticle_image img")):
        src = img.get("data-original-src") or img.get("src")
        if not src:
            continue
        # Prefer live CDN from data-bg or reconstruct — offline fixtures are local
        url = urljoin(base_url + "/", src)
        # Try data-bg absolute
        if img.get("data-bg") and img["data-bg"].startswith("http"):
            url = img["data-bg"]
        if url in seen or "logo" in url.lower():
            continue
        seen.add(url)
        images.append(PropertyImage(image_url=url, image_type="gallery" if i else "thumbnail", sort_order=i))
    return images


def _parse_links(soup: BeautifulSoup, *, base_url: str) -> list[PropertyLink]:
    links: list[PropertyLink] = []
    for ifr in soup.select("iframe[src]"):
        src = ifr.get("src", "")
        if "spacely" in src or "cloudfront" in src or "viewer" in src or "6575" in src:
            links.append(PropertyLink(link_type="panorama", url=urljoin(base_url + "/", src), label="3Dパノラマ"))
    for a in soup.select("a[href*='google.com/maps'], a[href*='maps.google']"):
        links.append(PropertyLink(link_type="map", url=a["href"], label="Google Map"))
        break
    return links


def _text(el) -> str | None:
    if el is None:
        return None
    t = el.get_text(strip=True)
    return t or None
