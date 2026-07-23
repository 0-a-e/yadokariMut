import os
import re
import json
import calendar
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup

_prefecture_name_to_slug = None
_prefecture_slug_to_name = None

def _load_prefecture_map():
    global _prefecture_name_to_slug, _prefecture_slug_to_name
    if _prefecture_name_to_slug is not None:
        return _prefecture_name_to_slug, _prefecture_slug_to_name
        
    name_to_slug = {}
    slug_to_name = {}
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                prefs = config.get("sources", {}).get("bratto", {}).get("prefectures", {})
                for slug, val in prefs.items():
                    name = val.get("name")
                    if name:
                        name_to_slug[name] = slug
                        slug_to_name[slug] = name
    except Exception:
        pass
    _prefecture_name_to_slug = name_to_slug
    _prefecture_slug_to_name = slug_to_name
    return name_to_slug, slug_to_name

def parse_money(text):
    """
    Extracts integer yen amount from money text.

    Prefer the number immediately before 「円」 so period suffixes like
    ``(月 75,000円/30日)`` parse as 75000 rather than 7500030.

    Examples:
      "4,900円/日" -> 4900
      "(月 75,000円/30日)" -> 75000
      "(週 14,350円/7日)" -> 14350
      "-1,080,000円/30日" -> -1080000
      "16,500" -> 16500
    """
    if not text:
        return None
    match = re.search(r'(-?[\d,]+)\s*円', text)
    if match:
        return int(match.group(1).replace(',', ''))
    cleaned = re.sub(r'[^\d-]', '', text)
    if cleaned in ('', '-'):
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None

def parse_area(text):
    """
    Extracts float value from area text (e.g. "19.16㎡" -> 19.16)
    """
    if not text:
        return None
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    return float(match.group(1)) if match else None

def parse_walk_minutes(text):
    """
    Extracts walk minutes integer (e.g. "徒歩 5分" -> 5)
    """
    if not text:
        return None
    match = re.search(r'(\d+)\s*分', text)
    return int(match.group(1)) if match else None

def parse_dates_from_text(text: str, default_year: int = None) -> tuple[str | None, str | None]:
    """Extract a start/end date range from Japanese campaign period text.

    Handles:
      - 2026年5月21日～2026年6月21日
      - 2026年5月1日から5月31日まで (year carried to end)
      - 2026年5月 (whole month)
      - 5月中 (current/default year, full month)
    """
    if not text:
        return None, None
        
    if default_year is None:
        default_year = datetime.now().year
        
    # Standardize range separators and spaces
    text = re.sub(r'\s+', '', text)
    
    # 1. First check for Year-Month-Day or Month-Day matches
    # Pattern: (Group 1: Year)? (Group 2: Month) (Group 3: Day)
    pattern_ymd = r'(?<!\d)(?:(\d{4})[年/\-])?(\d{1,2})[月/\-](\d{1,2})日?(?!\d)'
    matches_ymd = re.findall(pattern_ymd, text)
    
    parsed_dates = []
    current_year = default_year
    
    if matches_ymd:
        for y, m, d in matches_ymd:
            month = int(m)
            day = int(d)
            if y:
                current_year = int(y)
            # Validate month and day to avoid false positives (e.g. phone numbers or list numbers)
            if 1 <= month <= 12 and 1 <= day <= 31:
                # Clamp impossible days (e.g. Feb 31) to month end
                last = calendar.monthrange(current_year, month)[1]
                day = min(day, last)
                parsed_dates.append((current_year, month, day))
                
    if len(parsed_dates) >= 2:
        starts_on = f"{parsed_dates[0][0]:04d}-{parsed_dates[0][1]:02d}-{parsed_dates[0][2]:02d}"
        ends_on = f"{parsed_dates[1][0]:04d}-{parsed_dates[1][1]:02d}-{parsed_dates[1][2]:02d}"
        return starts_on, ends_on
    elif len(parsed_dates) == 1:
        starts_on = f"{parsed_dates[0][0]:04d}-{parsed_dates[0][1]:02d}-{parsed_dates[0][2]:02d}"
        # 「〜月末」「当月中」: single day start + 中 → end of that month
        if re.search(r'中|まで|末日', text):
            y, m, _d = parsed_dates[0]
            last_day = calendar.monthrange(y, m)[1]
            ends_on = f"{y:04d}-{m:02d}-{last_day:02d}"
            return starts_on, ends_on
        return starts_on, None
        
    # 2. If no YMD matches, check for Year-Month matches
    # Pattern: (Group 1: Year) (Group 2: Month)
    # e.g., 2026年5月, 2026/05
    pattern_ym = r'(?<!\d)(\d{4})[年/](\d{1,2})月?(?!\d)'
    matches_ym = re.findall(pattern_ym, text)
    
    if matches_ym:
        year = int(matches_ym[0][0])
        month = int(matches_ym[0][1])
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            starts_on = f"{year:04d}-{month:02d}-01"
            ends_on = f"{year:04d}-{month:02d}-{last_day:02d}"
            if len(matches_ym) >= 2:
                eyear = int(matches_ym[1][0])
                emonth = int(matches_ym[1][1])
                if 1 <= emonth <= 12:
                    elast_day = calendar.monthrange(eyear, emonth)[1]
                    ends_on = f"{eyear:04d}-{emonth:02d}-{elast_day:02d}"
            return starts_on, ends_on

    # 3. Month-only with 中 (e.g. 5月中にご契約) using default_year
    m_mid = re.search(r'(?<!\d)(\d{1,2})月中', text)
    if m_mid:
        month = int(m_mid.group(1))
        if 1 <= month <= 12:
            last_day = calendar.monthrange(default_year, month)[1]
            return (
                f"{default_year:04d}-{month:02d}-01",
                f"{default_year:04d}-{month:02d}-{last_day:02d}",
            )
            
    return None, None

def parse_japanese_era(text):
    """
    Parses built year and month from Japanese era (e.g. "昭和59年7月" -> (1984, 7))
    or western format (e.g. "200612" -> (2006, 12), "2006年12月" -> (2006, 12)).
    Returns (year, month) or (None, None).
    """
    if not text:
        return None, None
    text = text.strip()
    
    # Check 6-digit western number e.g. "200612"
    if re.match(r'^\d{6}$', text):
        return int(text[:4]), int(text[4:])
    
    # Western year and month e.g. "2006年12月"
    west_match = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月', text)
    if west_match:
        return int(west_match.group(1)), int(west_match.group(2))
    
    west_year_only = re.search(r'(\d{4})\s*年', text)
    if west_year_only:
        return int(west_year_only.group(1)), None

    # Japanese Eras
    era_match = re.search(r'(昭和|平成|令和)\s*(\d+|元)\s*年\s*(?:(\d{1,2})\s*月)?', text)
    if era_match:
        era = era_match.group(1)
        year_str = era_match.group(2)
        month_str = era_match.group(3)
        
        year_num = 1 if year_str == "元" else int(year_str)
        
        if era == "昭和":
            base = 1925
        elif era == "平成":
            base = 1988
        elif era == "令和":
            base = 2018
        else:
            return None, None
            
        year = base + year_num
        month = int(month_str) if month_str else None
        return year, month
        
    return None, None

def parse_list_page(html_content, target_url="https://www.000area-weekly.com/tokyo/search_list/"):
    """
    Parses property list from a search list page.
    Similar to poc_scraper.py list parser but returning clean structured data.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    room_elements = soup.select(".room_list_loop")
    
    page_info = None
    now_el = soup.select_one(".now_wrap p.now")
    if now_el:
        page_info = now_el.text.strip()
        
    next_link_el = soup.select_one(".to_next a")
    has_next = next_link_el is not None
    next_url = next_link_el.get("href") if next_link_el else None
    if next_url:
        next_url = urljoin(target_url, next_url)
    
    properties = []
    for el in room_elements:
        data = {}
        # Title and Detail URL
        title_el = el.select_one("h2.pc a")
        if title_el:
            data["title"] = title_el.text.strip()
            data["detail_url"] = urljoin(target_url, title_el.get("href", ""))
        else:
            continue
            
        # Room ID
        fav_btn = el.select_one(".favorite_btn")
        if fav_btn and fav_btn.get("data-room-id"):
            data["room_id"] = fav_btn.get("data-room-id")
        elif data["detail_url"]:
            parsed_url = urlparse(data["detail_url"])
            queries = parse_qs(parsed_url.query)
            data["room_id"] = queries.get("room_id", [None])[0]
        else:
            data["room_id"] = None
            
        if not data["room_id"]:
            continue
            
        # Images
        img_el = el.select_one(".image a img")
        if img_el:
            img_url = img_el.get("data-lazy-src") or img_el.get("src")
            data["thumbnail_url"] = urljoin(target_url, img_url) if img_url else None
        else:
            data["thumbnail_url"] = None
            
        madori_el = el.select_one(".image a.madori img")
        if madori_el:
            madori_url = madori_el.get("data-lazy-src") or madori_el.get("src")
            data["floorplan_url"] = urljoin(target_url, madori_url) if madori_url else None
        else:
            data["floorplan_url"] = None
            
        # Address
        addr_el = el.select_one(".addr")
        data["address"] = addr_el.text.strip() if addr_el else None
        
        # Access
        koutsu_divs = el.select(".koutsu div")
        data["access"] = [div.text.strip() for div in koutsu_divs if div.text.strip()]
        
        # Info block (築年, 間取り, 面積)
        info_el = el.select_one(".info")
        if info_el:
            info_texts = []
            for s in info_el.stripped_strings:
                parts = re.split(r"[\n/]", s)
                info_texts.extend([p.strip() for p in parts if p.strip()])
                
            data["construction_year"] = None
            data["room_layout"] = None
            data["area_size"] = None
            
            for text in info_texts:
                if text.startswith("築"):
                    data["construction_year"] = text.replace("築", "").strip()
                elif "㎡" in text:
                    data["area_size"] = text.strip()
                elif any(x in text for x in ["LDK", "DK", "K", "R"]):
                    data["room_layout"] = text.strip()
                else:
                    if re.search(r"\d+(\.\d+)?㎡", text):
                        data["area_size"] = text.strip()
        else:
            data["construction_year"] = None
            data["room_layout"] = None
            data["area_size"] = None
            
        # Features
        tag_elements = el.select(".label_list ul li.active")
        data["features"] = [tag.text.strip() for tag in tag_elements if tag.text.strip()]
        
        # Campaigns
        campaigns = []
        cam_boxes = el.select(".room_campaign .cam_box")
        for box in cam_boxes:
            label_el = box.select_one(".label")
            title_el = box.select_one(".title")
            if label_el or title_el:
                campaign = {
                    "type": label_el.text.strip() if label_el else None,
                    "title": title_el.text.strip() if title_el else None,
                    "details": {}
                }
                detail_items = box.select(".cam_body ul li")
                for item in detail_items:
                    th_el = item.select_one(".th")
                    td_el = item.select_one(".td")
                    if th_el and td_el:
                        key = th_el.text.strip().replace("【", "").replace("】", "")
                        campaign["details"][key] = td_el.text.strip()
                campaigns.append(campaign)
        data["campaigns"] = campaigns
        
        # Rent Plans
        rent_plans = {}
        plan_rows = el.select(".room_body_td_price .flex-sb")
        for row in plan_rows:
            plan_name_el = row.select_one(".w_plan")
            if not plan_name_el:
                continue
            plan_name = " ".join([s.strip() for s in plan_name_el.strings if s.strip()])
            
            price_container = row.select_one(".w_yachin")
            if not price_container:
                continue
                
            no_plan_el = price_container.select_one(".no_plan")
            if no_plan_el:
                rent_plans[plan_name] = {
                    "available": False,
                    "message": no_plan_el.text.strip()
                }
                continue
                
            plan_data = {"available": True}
            before_el = price_container.select_one(".before_price")
            if before_el:
                price_span = before_el.select_one(".price")
                total_span = before_el.select_one(".total")
                plan_data["original_daily_rent"] = price_span.text.strip() if price_span else None
                plan_data["original_monthly_total"] = total_span.text.strip() if total_span else None
                
            after_el = price_container.select_one(".after_price")
            if after_el:
                arrow_span = after_el.select_one(".arrow")
                price_span = after_el.select_one(".price")
                total_span = after_el.select_one(".total")
                campaign_label = arrow_span.text.replace("➡", "").strip() if arrow_span else None
                plan_data["discounted_daily_rent"] = price_span.text.strip() if price_span else None
                plan_data["discounted_monthly_total"] = total_span.text.strip() if total_span else None
                plan_data["discount_campaign_name"] = campaign_label
                
            rent_plans[plan_name] = plan_data
            
        data["rent_plans"] = rent_plans
        properties.append(data)
        
    return properties, page_info, has_next, next_url

def parse_detail_page(html_content, base_url="https://www.000area-weekly.com"):
    """
    Parses detailed information from a property detail page.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    detail_data = {}
    
    # 1. JSON-LD
    detail_data["json_ld"] = {}
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string or "")
            if data.get("@type") == "Apartment":
                detail_data["json_ld"] = data
                break
        except Exception:
            pass
            
    # 2. Spec Table (Table 0)
    spec_table = None
    tables = soup.find_all("table")
    for t in tables:
        # Check if first cell is '住所'
        th = t.find("th")
        if th and th.text.strip() == "住所":
            spec_table = t
            break
            
    specs = {}
    if spec_table:
        for tr in spec_table.find_all("tr"):
            ths = tr.find_all("th")
            tds = tr.find_all("td")
            
            # Row has 1 th and 1 td (which might have colspan)
            if len(ths) == 1 and len(tds) == 1:
                th_text = ths[0].text.strip()
                td = tds[0]
                
                if th_text == "交通":
                    # Extract raw access list from divs
                    access_divs = td.find_all("div")
                    if access_divs:
                        specs["交通"] = [d.text.strip() for d in access_divs if d.text.strip()]
                    else:
                        specs["交通"] = [s.strip() for s in td.stripped_strings if s.strip()]
                elif th_text == "基本設備":
                    # Extract equipment categories
                    categories = {}
                    current_cat = "その他"
                    for child in td.children:
                        if child.name == "div" and "setsubi_list" in child.get("class", []):
                            title_el = child.select_one(".title")
                            content_el = child.select_one(".setsubi_content")
                            if title_el and content_el:
                                cat_name = title_el.text.strip().lstrip("- ").strip()
                                spans = [sp.text.strip() for sp in content_el.find_all("span") if sp.text.strip()]
                                categories[cat_name] = spans
                        elif child.name == "p" and "title" in child.get("class", []):
                            current_cat = child.text.strip().lstrip("- ").strip()
                        elif child.name == "div" and "setsubi_content" in child.get("class", []):
                            spans = [sp.text.strip() for sp in child.find_all("span") if sp.text.strip()]
                            categories[current_cat] = spans
                    specs["基本設備"] = categories
                else:
                    specs[th_text] = td.text.strip()
            # Row has 2 th and 2 td (e.g. 間取り + 広さ)
            elif len(ths) == 2 and len(tds) == 2:
                for th, td in zip(ths, tds):
                    specs[th.text.strip()] = td.text.strip()
                    
    detail_data["specs"] = specs
    
    # 3. Price Table (Table 1)
    price_table = None
    for t in tables:
        th = t.find("th")
        if th and th.text.strip() == "プラン":
            price_table = t
            break
            
    rent_plans = []
    if price_table:
        # Headers are usually Row 0: ['プラン', '賃料', '管理費', '清掃費']
        for tr in price_table.find_all("tr")[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 4:
                plan_name_raw = cells[0].text.strip()
                # Remove extra spaces/newlines inside plan name
                plan_name = " ".join(plan_name_raw.split())
                
                rent_td = cells[1]
                management_td = cells[2]
                cleaning_td = cells[3]
                
                plan_info = {
                    "plan_name": plan_name,
                    "available": True,
                    "original_daily_rent": None,
                    "discounted_daily_rent": None,
                    "original_total": None,
                    "discounted_total": None,
                    "total_period_days": None,
                    "campaign_label": None,
                    "management_fee_daily": management_td.text.strip(),
                    "cleaning_fee": cleaning_td.text.strip(),
                    "raw_text": rent_td.text.strip()
                }
                
                # Check if unavailable
                if "取扱いはございません" in rent_td.text or "お取り扱いはございません" in rent_td.text or "満室" in rent_td.text:
                    plan_info["available"] = False
                else:
                    # Parse rent
                    cam_label_el = rent_td.select_one(".cam_label")
                    if cam_label_el:
                        plan_info["campaign_label"] = cam_label_el.text.strip()
                        
                    before_el = rent_td.select_one(".day .before")
                    defo_el = rent_td.select_one(".day .defo")
                    if before_el:
                        plan_info["original_daily_rent"] = before_el.text.strip()
                    if defo_el:
                        plan_info["discounted_daily_rent"] = defo_el.text.strip()
                        
                    # If there's no explicitly separated before/defo but there is text
                    if not before_el and not defo_el:
                        # Grab daily rent directly
                        price_color = rent_td.select_one(".price_color")
                        if price_color:
                            plan_info["discounted_daily_rent"] = price_color.text.strip()
                            
                    # Parse total period days
                    total_before = rent_td.select_one(".total .before")
                    total_defo = rent_td.select_one(".total .defo")
                    
                    if total_before:
                        plan_info["original_total"] = total_before.text.strip()
                    if total_defo:
                        plan_info["discounted_total"] = total_defo.text.strip()
                        
                    # Determine period days from total text (e.g. "(週 34,300円/7日)" or "(月 129,000円/30日)")
                    total_text = rent_td.text
                    period_match = re.search(r'/(\d+)\s*日', total_text)
                    if period_match:
                        plan_info["total_period_days"] = int(period_match.group(1))
                        
                rent_plans.append(plan_info)
                
    detail_data["rent_plans"] = rent_plans
    
    # 4. Campaigns in detail page
    campaigns = []
    cam_boxes = soup.select(".room_campaign .cam_box")
    for box in cam_boxes:
        label_el = box.select_one(".label")
        title_el = box.select_one(".title")
        if label_el or title_el:
            campaign = {
                "type": label_el.text.strip() if label_el else None,
                "title": title_el.text.strip() if title_el else None,
                "details": {}
            }
            detail_items = box.select(".cam_body ul li")
            for item in detail_items:
                th_el = item.select_one(".th")
                td_el = item.select_one(".td")
                if th_el and td_el:
                    key = th_el.text.strip().replace("【", "").replace("】", "")
                    campaign["details"][key] = td_el.text.strip()
            campaigns.append(campaign)
    detail_data["campaigns"] = campaigns

    # 4b. Official simulator cam_* JS objects (structured discounts)
    try:
        from campaign_structurer import extract_cam_js_objects
        detail_data["cam_js_objects"] = extract_cam_js_objects(html_content)
    except Exception:
        detail_data["cam_js_objects"] = []

    # 5. YouTube Links
    youtube_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "youtube.com" in href or "youtu.be" in href:
            youtube_links.append({
                "url": href,
                "label": a.text.strip() or "YouTube"
            })
    detail_data["youtube_links"] = youtube_links
    
    # 6. Lightbox images
    lightbox_links = soup.find_all("a", rel="lightbox")
    images = []
    for i, link in enumerate(lightbox_links):
        href = link.get("href")
        img_el = link.find("img")
        img_url = img_el.get("data-lazy-src") or img_el.get("src") if img_el else None
        
        # If href points to local file e.g. "./BraTTo...", let's prioritize img_url or clean it up
        full_href = urljoin(base_url, href) if href else None
        full_img_url = urljoin(base_url, img_url) if img_url else None
        
        images.append({
            "image_url": full_img_url or full_href,
            "sort_order": i
        })
    detail_data["images"] = images
    
    # 7. POINT description (prefer body .text so the "POINT" title is not included)
    point_el = (
        soup.select_one(".room_point .text")
        or soup.select_one(".point_text")
        or soup.select_one(".room_point")
    )
    if point_el:
        point_text = point_el.get_text(separator="\n", strip=True)
        # Strip residual "POINT" heading if the whole container was selected
        if point_text.upper().startswith("POINT"):
            point_text = point_text[5:].lstrip(" \t\n\r:：")
        detail_data["point_text"] = point_text or None
    else:
        detail_data["point_text"] = None

    return detail_data

def normalize_property(list_data, detail_data):
    """
    Combines and normalizes property list data and detail data.
    """
    normalized = {}
    
    # 1. Base property info
    normalized["source_site"] = "bratto"
    normalized["source_property_id"] = list_data.get("room_id")
    normalized["title"] = detail_data.get("json_ld", {}).get("name") or list_data.get("title")
    normalized["detail_url"] = list_data.get("detail_url")
    
    # Load prefecture maps from config.json
    name_to_slug, slug_to_name = _load_prefecture_map()

    # Address, Lat/Lng from JSON-LD or spec table or list data
    address = list_data.get("address")
    if not address and "specs" in detail_data and "住所" in detail_data["specs"]:
        address = detail_data["specs"]["住所"]

    # Precedence for prefecture_name:
    # 1. JSON-LD addressRegion (if available)
    # 2. list_data's prefecture_name (scraped from list page or input json)
    # 3. Parsed from address prefix
    # 4. Fallback default based on list_data's prefecture_slug
    # 5. Default "東京都"
    prefecture_name = None
    json_ld_addr = detail_data.get("json_ld", {}).get("address", {})
    if json_ld_addr:
        prefecture_name = json_ld_addr.get("addressRegion")
        municipality = json_ld_addr.get("addressLocality")
        street = json_ld_addr.get("streetAddress")
        if prefecture_name and municipality and street:
            address = f"{prefecture_name}{municipality}{street}"
    else:
        municipality = None

    if not prefecture_name:
        prefecture_name = list_data.get("prefecture_name")

    if not prefecture_name and address:
        for name in name_to_slug.keys():
            if address.startswith(name):
                prefecture_name = name
                break

    if not prefecture_name:
        pref_slug = list_data.get("prefecture_slug")
        if pref_slug:
            prefecture_name = slug_to_name.get(pref_slug)

    if not prefecture_name:
        prefecture_name = "東京都" # Default fallback

    # Precedence for prefecture_slug:
    # 1. list_data's prefecture_slug
    # 2. Map from prefecture_name
    # 3. Default "tokyo" (for "東京都" fallback)
    prefecture_slug = list_data.get("prefecture_slug")
    if not prefecture_slug:
        prefecture_slug = name_to_slug.get(prefecture_name)
    if not prefecture_slug:
        prefecture_slug = "tokyo"

    normalized["address"] = address
    normalized["prefecture_slug"] = prefecture_slug
    normalized["prefecture_name"] = prefecture_name
    normalized["municipality"] = municipality
    
    # Geocoding from JSON-LD
    lat = None
    lng = None
    geocode_source = None
    geocode_confidence = None
    
    json_ld_geo = detail_data.get("json_ld", {}).get("geo", {})
    if json_ld_geo:
        lat = float(json_ld_geo.get("latitude")) if json_ld_geo.get("latitude") else None
        lng = float(json_ld_geo.get("longitude")) if json_ld_geo.get("longitude") else None
        if lat and lng:
            geocode_source = "json-ld"
            geocode_confidence = 1.0
            
    normalized["lat"] = lat
    normalized["lng"] = lng
    normalized["geocode_source"] = geocode_source
    normalized["geocode_confidence"] = geocode_confidence
    
    # Layout and Area
    layout = list_data.get("room_layout")
    if "specs" in detail_data and "間取り" in detail_data["specs"]:
        layout = detail_data["specs"]["間取り"]
    normalized["layout"] = layout
    
    area_text = list_data.get("area_size")
    if "specs" in detail_data and "広さ" in detail_data["specs"]:
        area_text = detail_data["specs"]["広さ"]
    normalized["area_m2"] = parse_area(area_text)
    
    # Construction Year
    const_year_text = list_data.get("construction_year")
    if "specs" in detail_data and "築年数" in detail_data["specs"]:
        const_year_text = detail_data["specs"]["築年数"]
    normalized["construction_year_text"] = const_year_text
    
    built_year, built_month = parse_japanese_era(const_year_text)
    normalized["built_year"] = built_year
    normalized["built_month"] = built_month
    
    # Other specs
    specs = detail_data.get("specs", {})
    normalized["capacity_text"] = specs.get("入居可能人数")
    normalized["structure"] = specs.get("構造")
    normalized["floors_text"] = specs.get("階建")
    normalized["point_text"] = detail_data.get("point_text")
    normalized["availability_text"] = list_data.get("availability_text") # often empty in list, can be updated later
    
    # 2. Accesses
    normalized["accesses"] = []
    raw_access_list = specs.get("交通") or list_data.get("access", [])
    for idx, raw_access in enumerate(raw_access_list):
        # Parse access string
        line_name = None
        station_name = None
        walk_minutes = None
        
        # Try match: e.g. "京成本線 千住大橋駅 徒歩 4分"
        match = re.match(r'^(.*?)\s+(\S+駅)\s+徒歩\s*(\d+)\s*分', raw_access)
        if match:
            line_name = match.group(1).strip()
            station_name = match.group(2).strip()
            walk_minutes = int(match.group(3))
        else:
            # Fallback
            walk_minutes = parse_walk_minutes(raw_access)
            station_match = re.search(r'(\S+駅)', raw_access)
            if station_match:
                station_name = station_match.group(1)
                line_name = raw_access.split(station_name)[0].strip()
                
        normalized["accesses"].append({
            "line_name": line_name,
            "station_name": station_name,
            "walk_minutes": walk_minutes,
            "raw_text": raw_access,
            "sort_order": idx
        })
        
    # 3. Images
    normalized["images"] = []
    # Representative thumbnail and floorplan from list data
    if list_data.get("thumbnail_url"):
        normalized["images"].append({
            "image_url": list_data["thumbnail_url"],
            "image_type": "thumbnail",
            "alt_text": "代表画像",
            "sort_order": -2
        })
    if list_data.get("floorplan_url"):
        normalized["images"].append({
            "image_url": list_data["floorplan_url"],
            "image_type": "floorplan",
            "alt_text": "間取り図",
            "sort_order": -1
        })
    # Lightbox detail images
    for img in detail_data.get("images", []):
        normalized["images"].append({
            "image_url": img["image_url"],
            "image_type": "gallery",
            "alt_text": None,
            "sort_order": img["sort_order"]
        })
        
    # 4. Links
    normalized["links"] = []
    for link in detail_data.get("youtube_links", []):
        # Prevent official channels or other non-video links if needed, but keeping for now
        normalized["links"].append({
            "link_type": "youtube",
            "url": link["url"],
            "label": link["label"]
        })
        
    # 5. Rent Plans
    normalized["rent_plans"] = []
    detail_plans = detail_data.get("rent_plans", [])
    
    plan_code_map = {
        "s_short": ["sショート", "s-short", "1ヶ月未満"],
        "short": ["ショート", "1ヶ月~3ヶ月", "1～3ヶ月"],
        "middle": ["ミドル", "3ヶ月～6ヶ月", "3～6ヶ月"],
        "long": ["ロング", "6ヶ月以上"]
    }
    
    if detail_plans:
        for plan in detail_plans:
            # Determine plan code
            name_lower = plan["plan_name"].lower()
            plan_code = "other"
            for code, keywords in plan_code_map.items():
                if any(kw in name_lower for kw in keywords):
                    plan_code = code
                    break
                    
            original_daily = parse_money(plan["original_daily_rent"])
            discounted_daily = parse_money(plan["discounted_daily_rent"])
            
            # If no discounted but original exists, duplicate to discounted
            if original_daily and not discounted_daily:
                discounted_daily = original_daily
            elif discounted_daily and not original_daily:
                original_daily = discounted_daily
                
            original_tot = parse_money(plan["original_total"])
            discounted_tot = parse_money(plan["discounted_total"])
            
            if original_tot and not discounted_tot:
                discounted_tot = original_tot
            elif discounted_tot and not original_tot:
                original_tot = discounted_tot
                
            management = parse_money(plan["management_fee_daily"])
            cleaning = parse_money(plan["cleaning_fee"])
            
            normalized["rent_plans"].append({
                "plan_code": plan_code,
                "plan_name": plan["plan_name"],
                "duration_text": plan["plan_name"].split()[-1] if len(plan["plan_name"].split()) > 1 else plan["plan_name"],
                "available": 1 if plan["available"] else 0,
                "campaign_label": plan["campaign_label"],
                "original_daily_rent_yen": original_daily,
                "discounted_daily_rent_yen": discounted_daily,
                "original_total_yen": original_tot,
                "discounted_total_yen": discounted_tot,
                "total_period_days": plan["total_period_days"],
                "management_fee_daily_yen": management,
                "cleaning_fee_yen": cleaning,
                "raw_text": plan["raw_text"]
            })
    else:
        # Fallback to list page rent plans
        for p_name, p_val in list_data.get("rent_plans", {}).items():
            name_lower = p_name.lower()
            plan_code = "other"
            for code, keywords in plan_code_map.items():
                if any(kw in name_lower for kw in keywords):
                    plan_code = code
                    break
            
            if p_val.get("available"):
                orig_daily = parse_money(p_val.get("original_daily_rent"))
                disc_daily = parse_money(p_val.get("discounted_daily_rent"))
                orig_tot = parse_money(p_val.get("original_monthly_total"))
                disc_tot = parse_money(p_val.get("discounted_monthly_total"))
                
                # Determine period from total text e.g. "月 111,000円/30日" or "週 34,300円/7日"
                period = None
                tot_text = p_val.get("discounted_monthly_total") or p_val.get("original_monthly_total") or ""
                period_match = re.search(r'/(\d+)\s*日', tot_text)
                if period_match:
                    period = int(period_match.group(1))
                
                normalized["rent_plans"].append({
                    "plan_code": plan_code,
                    "plan_name": p_name,
                    "duration_text": p_name.split()[-1] if len(p_name.split()) > 1 else p_name,
                    "available": 1,
                    "campaign_label": p_val.get("discount_campaign_name"),
                    "original_daily_rent_yen": orig_daily or disc_daily,
                    "discounted_daily_rent_yen": disc_daily or orig_daily,
                    "original_total_yen": orig_tot or disc_tot,
                    "discounted_total_yen": disc_tot or orig_tot,
                    "total_period_days": period,
                    "management_fee_daily_yen": None,
                    "cleaning_fee_yen": None,
                    "raw_text": json.dumps(p_val)
                })
            else:
                normalized["rent_plans"].append({
                    "plan_code": plan_code,
                    "plan_name": p_name,
                    "duration_text": p_name.split()[-1] if len(p_name.split()) > 1 else p_name,
                    "available": 0,
                    "campaign_label": None,
                    "original_daily_rent_yen": None,
                    "discounted_daily_rent_yen": None,
                    "original_total_yen": None,
                    "discounted_total_yen": None,
                    "total_period_days": None,
                    "management_fee_daily_yen": None,
                    "cleaning_fee_yen": None,
                    "raw_text": p_val.get("message", "Unavailable")
                })
                
    # 6. Features
    normalized["features"] = []
    detail_features = specs.get("基本設備", {})
    if detail_features:
        for cat, list_tags in detail_features.items():
            for tag in list_tags:
                normalized["features"].append({
                    "feature_name": tag,
                    "feature_category": cat,
                    "raw_text": tag
                })
    else:
        # Fallback to list tags
        for tag in list_data.get("features", []):
            normalized["features"].append({
                "feature_name": tag,
                "feature_category": "list_tag",
                "raw_text": tag
            })
            
    # 7. Campaigns (structured mechanically; merge official cam_* when present)
    from campaign_structurer import structure_campaign

    normalized["campaigns"] = []
    cams = detail_data.get("campaigns") or list_data.get("campaigns", [])
    cam_js_objects = detail_data.get("cam_js_objects") or []
    for cam in cams:
        period_text = cam.get("details", {}).get("対象期間", "") if "details" in cam else ""
        condition_text = cam.get("details", {}).get("対象条件") if "details" in cam else None
        content = (
            cam.get("details", {}).get("内容") or cam.get("title")
            if "details" in cam
            else cam.get("title")
        )
        starts_on, ends_on = parse_dates_from_text(period_text)
        structured = structure_campaign(
            campaign_type=cam.get("type"),
            title=cam.get("title"),
            content=content,
            period_text=period_text,
            condition_text=condition_text,
            cam_objects=cam_js_objects,
            starts_on=starts_on,
            ends_on=ends_on,
        )
        entry = {
            "campaign_type": cam.get("type"),
            "title": cam.get("title"),
            "content": content,
            "target_period_text": period_text,
            "target_condition_text": condition_text,
            "starts_on": structured.get("starts_on"),
            "ends_on": structured.get("ends_on"),
            "raw_json": json.dumps(cam, ensure_ascii=False),
            "target_plan_code": structured.get("target_plan_code"),
            "discount_unit": structured.get("discount_unit"),
            "discount_value": structured.get("discount_value"),
            "discount_max_yen": structured.get("discount_max_yen"),
            "period_max_days": structured.get("period_max_days"),
            "stay_min_days": structured.get("stay_min_days"),
            "stay_max_days": structured.get("stay_max_days"),
            "contract_within_days": structured.get("contract_within_days"),
            "package_rent_benefit_yen": structured.get("package_rent_benefit_yen"),
            "package_cleaning_benefit_yen": structured.get("package_cleaning_benefit_yen"),
            "package_fee_benefit_yen": structured.get("package_fee_benefit_yen"),
            "package_total_benefit_yen": structured.get("package_total_benefit_yen"),
            "structure_source": structured.get("structure_source"),
            "parse_ok": structured.get("parse_ok"),
            "parse_warnings": structured.get("parse_warnings_json"),
        }
        normalized["campaigns"].append(entry)
        
    return normalized
