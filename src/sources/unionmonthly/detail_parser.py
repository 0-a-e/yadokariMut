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
from domain.pricing import UNION_DURATION_BANDS
from sources.base import ListCard

BASE = "https://www.unionmonthly.jp"
PARSER_VERSION = "unionmonthly-detail-1.0"

TAB_TO_KEY = {
    "ショート": "short",
    "ミドル": "middle",
    "ロング": "long",
    "スーパーショート": "s_short",
    "sショート": "s_short",
}


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
    lat, lng = _parse_geo(html, soup)
    pref_name, municipality = _split_pref_muni(address)
    prefecture_slug = card.prefecture_slug or _pref_slug_from_url(detail_url or card.detail_url)

    accesses = _parse_accesses(soup, html)
    features = _parse_features(soup)
    plans = _parse_price_plans(soup)
    campaigns = _parse_campaigns(soup)
    images = _parse_images(soup, base_url=base_url)
    links = _parse_links(soup, base_url=base_url)

    min_stay = None
    if "最低契約" in soup.get_text():
        m = re.search(r"最低契約日数[^\d]*(\d+)\s*([かヶヵカ]月|日)", soup.get_text())
        if m:
            n = int(m.group(1))
            min_stay = n * 30 if "月" in m.group(2) else n

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
        min_stay_days=min_stay,
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
    if not text:
        return None, None, None
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})?\s*月?", text)
    if m:
        year = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else None
        return year, month, text.strip()
    return None, None, text.strip()


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
    prefs = [
        "北海道", "東京都", "大阪府", "京都府",
        "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
        "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "神奈川県",
        "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
        "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "兵庫県",
        "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県",
        "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
        "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
    ]
    for p in prefs:
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
        t = li.get_text(" ", strip=True)
        if "徒歩" in t or "駅" in t:
            candidates.append(t)
    meta = soup.select_one('meta[name="description"]')
    if meta and meta.get("content"):
        m = re.search(r"最寄り駅[：:]\s*([^。]+)", meta["content"])
        if m:
            candidates.append(m.group(1).strip())
    # table 交通 rows
    for th in soup.find_all("th"):
        if "交通" in th.get_text():
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
        line, station, walk = _split_access(raw)
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


def _split_access(raw: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    walk = None
    m = re.search(r"徒歩\s*(\d+)\s*分", raw)
    if m:
        walk = int(m.group(1))
    station = None
    m2 = re.search(r"([^\s　]+駅)", raw)
    if m2:
        station = m2.group(1)
    line = None
    if station and station in raw:
        line = raw.split(station)[0].strip(" 　/")
        if not line:
            line = None
    return line, station, walk


def _parse_features(soup: BeautifulSoup) -> list[PropertyFeature]:
    features: list[PropertyFeature] = []
    cat_map = {
        "建物設備": "building",
        "室内設備": "room",
        "家具家電": "appliance",
        "アメニティ": "supplies",
        "その他": "other",
    }
    for table in soup.select("table.facility_table"):
        for tr in table.select("tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if not th or not td:
                continue
            cat_label = th.get_text(strip=True)
            cat = cat_map.get(cat_label, "other")
            parts = re.split(r"[、,，]", td.get_text("、", strip=True))
            for p in parts:
                name = p.strip()
                if name:
                    features.append(PropertyFeature(feature_name=name, feature_category=cat, raw_text=name))
    # tag chips
    for el in soup.select(".facility_list li, .entry_tag li, .tagList li"):
        name = el.get_text(strip=True)
        if name:
            features.append(PropertyFeature(feature_name=name, feature_category="list_tag", raw_text=name))
    # dedupe
    seen: set[tuple[str, str | None]] = set()
    out: list[PropertyFeature] = []
    for f in features:
        key = (f.feature_name, f.feature_category)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _parse_price_plans(soup: BeautifulSoup) -> list[PricePlan]:
    tabs = [li.get_text(strip=True) for li in soup.select(".outline_plan_tab_item")]
    panels = soup.select(".outline_plan_tab_panel")
    plans: list[PricePlan] = []

    for i, panel in enumerate(panels):
        tab_name = tabs[i] if i < len(tabs) else f"plan_{i}"
        plan_key = TAB_TO_KEY.get(tab_name, re.sub(r"\W+", "_", tab_name).lower() or f"plan_{i}")
        dmin, dmax = UNION_DURATION_BANDS.get(plan_key, (1, None))

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
                    bs = [_money(b.get_text()) for b in dl.select("b")]
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
                    v = _money(box.get_text())
                    if v is not None:
                        right_bs.append(v)
                left_rent = None
                for dl in block.select(".outline_price_box_left dl, .normal_price_list"):
                    dt = dl.select_one("dt")
                    if dt and "賃料" in dt.get_text():
                        left_rent = _money(dl.get_text())
                # Better pass: walk price boxes
                rent_orig, rent_cur, mgmt = _parse_uchiwake(block, rent_orig, rent_cur, mgmt)
            elif "清掃" in ttl:
                nums = [_money(b.get_text()) for b in block.select("b")]
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
                    rent_orig = _money(n.get_text())
                if c:
                    rent_cur = _money(c.get_text())
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

        plans.append(
            PricePlan(
                plan_key=plan_key,
                plan_name=tab_name if duration_text is None else f"{tab_name}（{duration_text}）",
                duration_min_days=dmin,
                duration_max_days=dmax,
                available=True,
                presentation_unit="per_month",
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
                left_val = _money(left.get_text()) if left else None
                right_val = _money(right.get_text()) if right else None
                if "賃料" in label:
                    rent_orig = left_val if left_val is not None else rent_orig
                    rent_cur = right_val if right_val is not None else rent_cur
                elif "共益" in label:
                    # often same both sides
                    mgmt = right_val if right_val is not None else left_val
        if "清掃" in ttl:
            left = block.select_one(".outline_price_box_left") or block.select_one(".normal_price_list")
            right = block.select_one(".outline_price_box_right") or block.select_one(".campaign_price_list")
            nums = [_money(b.get_text()) for b in block.select("b")]
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


def _money(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _text(el) -> str | None:
    if el is None:
        return None
    t = el.get_text(strip=True)
    return t or None
