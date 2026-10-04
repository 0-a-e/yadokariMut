"""BraTTo 詳細ページの抽出 (JSON-LD / 規格テーブル / プラン / キャンペーン等)。"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from sources.bratto.campaign_structurer import extract_cam_js_objects


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
