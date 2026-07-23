"""Union Monthly list page parser."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from sources.base import ListCard

BASE = "https://www.unionmonthly.jp"


def parse_list_html(
    html: str,
    *,
    base_url: str = BASE,
    prefecture_slug: str | None = None,
    prefecture_name: str | None = None,
) -> list[ListCard]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ListCard] = []
    for item in soup.select("div.list_item"):
        card = _parse_item(item, base_url=base_url, prefecture_slug=prefecture_slug, prefecture_name=prefecture_name)
        if card:
            cards.append(card)
    return cards


def extract_total_count(html: str) -> int | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(r"([\d,]+)\s*件", text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_item(
    item,
    *,
    base_url: str,
    prefecture_slug: str | None,
    prefecture_name: str | None,
) -> Optional[ListCard]:
    external_id = item.get("data-troom_id")
    if not external_id:
        return None

    name_el = item.select_one("h2.gArticle_name")
    title = name_el.get_text(strip=True) if name_el else None

    detail_url = None
    link = item.select_one("a.u-btn01") or item.select_one("a[href*='/']")
    if link and link.get("href"):
        detail_url = urljoin(base_url + "/", link["href"])
    if not detail_url and prefecture_slug:
        detail_url = f"{base_url}/{prefecture_slug}/{external_id}/"

    price = None
    price_el = item.select_one("p.gArticle_price b")
    if price_el:
        digits = re.sub(r"[^\d]", "", price_el.get_text())
        if digits:
            price = int(digits)

    address = None
    for li in item.select("ul.gArticle_infoList li"):
        if li.select_one("i.icon-marker") or "icon-marker" in " ".join(li.get("class") or []):
            address = li.get_text(strip=True)
            break
    if not address:
        form = item.select_one("form[id^='form_contact']")
        if form:
            inp = form.select_one("input[name='room_address']")
            if inp and inp.get("value"):
                address = inp["value"]

    thumb = None
    img = item.select_one("div.gArticle_image img")
    if img:
        src = img.get("data-original-src") or img.get("src")
        if src:
            thumb = urljoin(base_url + "/", src)

    return ListCard(
        external_id=str(external_id),
        detail_url=detail_url or f"{base_url}/{external_id}/",
        title=title,
        address=address,
        list_price_yen=price,
        thumbnail_url=thumb,
        prefecture_slug=prefecture_slug,
        prefecture_name=prefecture_name,
    )
