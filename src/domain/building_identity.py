"""建物名寄せ語彙: address_key 正規化とソース別建物名抽出.

docs/building-aggregation-design.md §5 の正本実装。名寄せの決定的キーは
「正規化住所(address_key)」のみ(クロスソースの建物名はブランド名が別物と
いう本番実測に基づく)。建物名抽出はソース別の title 規則から行い、
名寄せキーには使わず検証信号(dry-run レポートの要確認検出)として使う。

実測根拠(2026-10-08 本番 DB・docs/building-aggregation-design.md §2):
- unionmonthly title は「建物名 部屋番号 間取り・ベッド【キャンペーン】」形で
  建物名プレフィックス一致率 99.4%(956 グループ中 950)
- bratto title は「建物名（タイプ接尾辞）」形で部屋番号を含まない
"""

from __future__ import annotations

import re
import unicodedata

# 末尾のタイプ/属性接尾辞: 「（Ａタイプ）」「(Bタイプ)」「【プラチナタイプ】」等。
# 対応する閉じ括弧までを含めて剥がす(全角/半角・丸/角の組合せ)。
_BRATTO_SUFFIX = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]\s*$")

# 丁目表記の統一: bratto は「西新宿8丁目-3-37」、unionmonthly は「西新宿8-3-37」
# と書くため、address_key 完全一致が両者の同一建物を取りこぼす(2026-10-09
# 本番監査で発見・ユニオンマンスリー西新宿駅前１×BraTTo新宿新都心 等)。
# 「(\d+)丁目」+直後の任意の区切り 1 文字を「\1-」へ畳める。漢数字の丁目
# (「八丁目」等)は対象外(NFKC で変換されないため。実データはアラビア数字のみ)。
_CHOME_RE = re.compile(r"(\d+)丁目[-ー−]?")


def normalize_address_key(address: str | None) -> str | None:
    """住所 → 名寄せキー(strip + NFKC + 空白除去 + 丁目表記統一・設計 §5).

    住所は両ソースとも号室なしの建物単位(survey §2.2)のため、この正規化で
    ソース間表記差(スペース挿入・丁目表記等)を畳める。NFKC で全角数字・英字・
    全角ハイフンも半角化される。
    """
    if not address:
        return None
    key = unicodedata.normalize("NFKC", address).strip()
    key = re.sub(r"\s+", "", key)
    key = _CHOME_RE.sub(r"\1-", key)
    return key.rstrip("-") or None


def extract_building_name(source_site: str, title: str | None) -> str | None:
    """title → ソース別の建物名(検証信号用・名寄せキーにはしない).

    - bratto: 末尾の（…）/【…】タイプ接尾辞を剥がした残り全体
    - その他(unionmonthly 含む): 最初の空白区切りトークン(部屋番号の手前まで)
    """
    if not title:
        return None
    text = title.strip()
    if not text:
        return None
    if source_site == "bratto":
        prev: str | None = None
        while prev != text:
            prev = text
            text = _BRATTO_SUFFIX.sub("", text).strip()
        return text or None
    match = re.match(r"\S+", text)
    return match.group(0) if match else (text or None)
