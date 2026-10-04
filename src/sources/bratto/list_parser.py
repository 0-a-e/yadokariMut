"""BraTTo 一覧ページの抽出 (検索結果 → 物件 dict リスト)。

スカラー値のテキスト解釈は sources.parsing、正規化は normalize.py の担当。
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup


def parse_pagination(soup, target_url: str) -> tuple[str | None, bool, str | None]:
    """ページ情報テキストと「次へ」リンクの有無・URL を抽出する。

    Returns:
        (page_info, has_next, next_url)
        has_next / next_url は SourceAdapter.has_next の終端判定にも使う。
    """
    page_info = None
    now_el = soup.select_one(".now_wrap p.now")
    if now_el:
        page_info = now_el.text.strip()

    next_link_el = soup.select_one(".to_next a")
    has_next = next_link_el is not None
    next_url = next_link_el.get("href") if next_link_el else None
    if next_url:
        next_url = urljoin(target_url, next_url)
    return page_info, has_next, next_url


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
