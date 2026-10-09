"""メディア取得URLの正規化(サイト別知識のSSOT・docs/media-storage-rustfs-plan.md §2.6)。

``property_images.image_url`` はスクレイパが保存した「表示用の正本URL」であり、
そのまま取得するとプロキシ経由で再エンコードされ品質が落ちる形式がある
(実測 §1.6: unionmonthly ``img_out.php`` は同解像度のまま低ビットレートに
再エンコード)。メディア取得時のみ本モジュールで実体URLへ正規化する
(DB 保存値は書き換えない・FE のフォールバック表示も正本URLのまま)。

サイト別ルールは本モジュールの ``_RESOLVERS`` に集約し、呼び出し側
(``store/media.py`` のみ)に if-site 分岐を置かない。
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

_UNIONMONTHLY_HOSTS = frozenset({"www.unionmonthly.jp", "unionmonthly.jp"})


def _unwrap_unionmonthly(url: str) -> str:
    """``img_out.php?img_data=<実体URL>`` を実体URLへ unwrap する。

    実体(``unionmonthly-img.jp``)は Referer 無しで直接取得でき、progressive
    JPEG の高品質版が得られる(§1.6 実測)。形式が合わない場合は無処理。
    """
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in _UNIONMONTHLY_HOSTS:
        return url
    if not parsed.path.rstrip("/").endswith("/img_out.php"):
        return url
    inner = (parse_qs(parsed.query).get("img_data") or [""])[0].strip()
    if inner.startswith(("http://", "https://")):
        return inner
    return url


# サイト別リゾルバの正本。新サイトの取得時正規化はここに追加する。
_RESOLVERS = {
    "unionmonthly": _unwrap_unionmonthly,
}


def resolve_media_url(source_site: str | None, image_url: str) -> str:
    """取得用URLへ正規化する(既知サイト以外は無処理)。"""
    resolver = _RESOLVERS.get(source_site or "")
    return resolver(image_url) if resolver else image_url
