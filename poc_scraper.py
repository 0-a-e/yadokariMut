#!/usr/bin/env python3
import os
import sys
import json
import time
import re
import argparse
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

# デフォルトのスクレイピング対象URL
TARGET_URL = "https://www.000area-weekly.com/tokyo/search_list/"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

def parse_room_element(room_soup):
    """
    1つの物件要素 (.room_list_loop) から物件情報を抽出するパーサー
    """
    data = {}

    # 1. 物件名と詳細ページURL
    title_el = room_soup.select_one("h2.pc a")
    if title_el:
        data["title"] = title_el.text.strip()
        relative_url = title_el.get("href", "")
        data["detail_url"] = urljoin(TARGET_URL, relative_url)
    else:
        data["title"] = None
        data["detail_url"] = None

    # 2. 物件ID (Room ID)
    # お気に入り登録ボタンの data-room-id から取得するのが最も確実
    fav_btn = room_soup.select_one(".favorite_btn")
    if fav_btn and fav_btn.get("data-room-id"):
        data["room_id"] = fav_btn.get("data-room-id")
    elif data["detail_url"]:
        # detail_url から抽出を試みる
        parsed_url = urlparse(data["detail_url"])
        queries = parse_qs(parsed_url.query)
        data["room_id"] = queries.get("room_id", [None])[0]
    else:
        data["room_id"] = None

    # 3. 画像URL
    # 遅延読み込みを考慮して data-lazy-src を優先取得、なければ src
    # 外観画像
    img_el = room_soup.select_one(".image a img")
    if img_el:
        img_url = img_el.get("data-lazy-src") or img_el.get("src")
        data["image_url"] = urljoin(TARGET_URL, img_url) if img_url else None
    else:
        data["image_url"] = None

    # 間取り図画像
    madori_el = room_soup.select_one(".image a.madori img")
    if madori_el:
        madori_url = madori_el.get("data-lazy-src") or madori_el.get("src")
        data["madori_url"] = urljoin(TARGET_URL, madori_url) if madori_url else None
    else:
        data["madori_url"] = None

    # 4. 住所
    addr_el = room_soup.select_one(".addr")
    data["address"] = addr_el.text.strip() if addr_el else None

    # 5. 交通アクセス (複数路線あるためリスト化)
    koutsu_divs = room_soup.select(".koutsu div")
    data["access"] = [div.text.strip() for div in koutsu_divs if div.text.strip()]

    # 6. 建物情報 (築年、間取り、専有面積)
    info_el = room_soup.select_one(".info")
    if info_el:
        # <br> 等で区切られているテキストを分解し、さらに改行やスラッシュで細分化する
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
            elif "LDK" in text or "DK" in text or "K" in text or "R" in text:
                data["room_layout"] = text.strip()
            else:
                # フォールバック処理
                if re.search(r"\d+(\.\d+)?㎡", text):
                    data["area_size"] = text.strip()
    else:
        data["construction_year"] = None
        data["room_layout"] = None
        data["area_size"] = None

    # 7. 設備・特徴タグ
    # active クラスが付与されているものが「対応している設備」
    tag_elements = room_soup.select(".label_list ul li.active")
    data["features"] = [tag.text.strip() for tag in tag_elements if tag.text.strip()]

    # 8. キャンペーン情報
    campaigns = []
    cam_boxes = room_soup.select(".room_campaign .cam_box")
    for box in cam_boxes:
        label_el = box.select_one(".label")
        title_el = box.select_one(".title")
        if label_el or title_el:
            campaign = {
                "type": label_el.text.strip() if label_el else None,
                "title": title_el.text.strip() if title_el else None,
                "details": {}
            }
            # キャンペーンの th / td ペアがあれば抽出
            detail_items = box.select(".cam_body ul li")
            for item in detail_items:
                th_el = item.select_one(".th")
                td_el = item.select_one(".td")
                if th_el and td_el:
                    key = th_el.text.strip().replace("【", "").replace("】", "")
                    campaign["details"][key] = td_el.text.strip()
            campaigns.append(campaign)
    data["campaigns"] = campaigns

    # 9. 料金プラン情報
    rent_plans = {}
    plan_rows = room_soup.select(".room_body_td_price .flex-sb")
    for row in plan_rows:
        plan_name_el = row.select_one(".w_plan")
        if not plan_name_el:
            continue
        
        # プラン名 (例: "ショート 1～3ヶ月" のように結合)
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
        
        # 割引前料金 (before_price)
        before_el = price_container.select_one(".before_price")
        if before_el:
            price_span = before_el.select_one(".price")
            total_span = before_el.select_one(".total")
            plan_data["original_daily_rent"] = price_span.text.strip() if price_span else None
            plan_data["original_monthly_total"] = total_span.text.strip() if total_span else None
            
        # 割引後料金 (after_price)
        after_el = price_container.select_one(".after_price")
        if after_el:
            arrow_span = after_el.select_one(".arrow")
            price_span = after_el.select_one(".price")
            total_span = after_el.select_one(".total")
            
            # "早割 ➡" などから矢印等を除去してキャンペーン名にする
            campaign_label = arrow_span.text.replace("➡", "").strip() if arrow_span else None
            
            plan_data["discounted_daily_rent"] = price_span.text.strip() if price_span else None
            plan_data["discounted_monthly_total"] = total_span.text.strip() if total_span else None
            plan_data["discount_campaign_name"] = campaign_label
            
        rent_plans[plan_name] = plan_data
        
    data["rent_plans"] = rent_plans

    return data

def parse_html_content(html_content):
    """
    指定されたHTML文字列から全物件情報をパースする
    """
    soup = BeautifulSoup(html_content, "html.parser")
    room_elements = soup.select(".room_list_loop")
    
    # ページ情報の抽出 (例: "436件中21〜30件")
    page_info = None
    now_el = soup.select_one(".now_wrap p.now")
    if now_el:
        page_info = now_el.text.strip()
        
    # 「もっと見る」リンクの存在確認
    next_link_el = soup.select_one(".to_next a")
    has_next = next_link_el is not None
    next_url = next_link_el.get("href") if next_link_el else None
    
    properties = []
    for el in room_elements:
        try:
            prop_data = parse_room_element(el)
            properties.append(prop_data)
        except Exception as e:
            print(f"Error parsing a room element: {e}", file=sys.stderr)
            
    return properties, page_info, has_next, next_url

def main():
    parser = argparse.ArgumentParser(description="BraTToマンスリー物件情報 スクレイピングPoC")
    parser.add_argument("--test-file", type=str, help="ローカルのHTMLファイルを指定して解析テストを実行します。")
    parser.add_argument("--out", type=str, default="properties.json", help="出力先JSONファイルのパス (デフォルト: properties.json)")
    parser.add_argument("--max-pages", type=int, default=50, help="スクレイピングする最大ページ数 (デフォルト: 50)")
    parser.add_argument("--delay", type=float, default=1.5, help="リクエスト間のスリープ時間秒数 (デフォルト: 1.5)")
    args = parser.parse_args()

    # --- テストモード (ローカルHTMLファイルの解析) ---
    if args.test_file:
        print(f"=== テストモード: {args.test_file} を解析中 ===")
        if not os.path.exists(args.test_file):
            print(f"Error: ファイルが見つかりません: {args.test_file}", file=sys.stderr)
            sys.exit(1)
            
        with open(args.test_file, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        properties, page_info, has_next, next_url = parse_html_content(html_content)
        
        print(f"解析成功:")
        print(f" - 物件数: {len(properties)}件")
        print(f" - ページ情報: {page_info}")
        print(f" - 次ページ有無: {has_next} (URL: {next_url})")
        
        # 最初の物件のサンプル表示
        if properties:
            print("\n--- 最初の物件のパース結果サンプル ---")
            print(json.dumps(properties[0], ensure_ascii=False, indent=2))
            
        # JSONファイルへ出力
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(properties, f, ensure_ascii=False, indent=2)
        print(f"\n結果を {args.out} に書き込みました。")
        sys.exit(0)

    # --- 本番スクレイピングモード (オンライン取得) ---
    print("=== オンラインスクレイピングを開始します ===")
    all_properties = []
    page = 1
    
    while page <= args.max_pages:
        url = f"{TARGET_URL}?pn={page}"
        print(f"ページ {page} を取得中... URL: {url}")
        
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            if response.status_code == 404:
                print(f"ページ {page} が見つかりません (404)。スクレイピングを終了します。")
                break
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"HTTPリクエストエラー: {e}", file=sys.stderr)
            break
            
        properties, page_info, has_next, next_url = parse_html_content(response.text)
        print(f" -> 取得件数: {len(properties)}件 ({page_info})")
        
        if not properties:
            print("物件が見つかりませんでした。スクレイピングを終了します。")
            break
            
        all_properties.extend(properties)
        
        # 次のページリンクが明示的にない場合は終了
        if not has_next:
            print("次ページのリンクが存在しません。最終ページに到達しました。")
            break
            
        # 次のページループの準備
        page += 1
        
        # サーバー負荷軽減のウェイト
        if page <= args.max_pages:
            time.sleep(args.delay)
            
    # 全取得データをJSONに書き出し
    print(f"\n=== スクレイピング完了 ===")
    print(f"総取得物件数: {len(all_properties)}件")
    
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_properties, f, ensure_ascii=False, indent=2)
        
    print(f"データを {args.out} に保存しました。")

if __name__ == "__main__":
    main()
