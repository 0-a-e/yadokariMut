"""サイト共通の機能カテゴリ辞書(SSOT・決定 1〜19)。

設計正本: ``docs/feature-category-unification-design.md``。
初期マッピング: 2026-10-08 本番 DB 実測 160 ユニーク語彙の仕分け(設計 §7-2 確定)。
    feature 単位 code 80(単純 70 + 複合 10)/ 親 code 5 / 横断 code 3 / NON_FILTER 4 語彙。

code 体系(決定 18):

    単純 code   ``auto_lock``                 — include を持つ通常カテゴリ
    複合 code   ``bicycle_parking.fee_free``  — 「親 code.修飾語」。include を持つ(feature 単位)
    親 code     ``bicycle_parking``           — include を持たない束ね code(子 code の和で導出)
    横断 code   ``fee_free``                  — 修飾語のみ。解決糖衣(単独・併用可・トグル非掲載・設計 §3.2)

include は DB 生値をそのまま保持し、突合は両辺正規化(strip + NFKC + casefold)
で行う(§7-7 確定 — 本番 160 語彙に正規化で畳まる組は無し)。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

FeatureGroup = Literal["facility", "condition", "contract", "other"]
FacilitySub = Literal["appliance", "furniture", "room", "building", "amenity"]


@dataclass(frozen=True)
class FeatureCategory:
    """カテゴリ辞書の 1 エントリ(決定 14・18)。"""

    code: str                 # 'washing_machine' / 複合語は 'bicycle_parking.fee_free'
    label: str                # 表示名。不変条件: label ∈ include(決定 14)
    include: tuple[str, ...]  # DB 実値の完全一致集合(生値保持・両辺正規化で突合)
    group: FeatureGroup       # 上位分類(決定 18)
    sub: FacilitySub | None   # 設備内サブ分類。facility のみ設定、それ以外は None


FEATURE_CATEGORIES: tuple[FeatureCategory, ...] = (
    # --- facility / appliance ---
    FeatureCategory("bluetooth_speaker", 'Bluetoothスピーカー', ('Bluetoothスピーカー',), "facility", "appliance"),
    FeatureCategory("clock", '時計', ('時計',), "facility", "appliance"),
    FeatureCategory("electric_stove", '電気コンロ', ('電気コンロ',), "facility", "appliance"),
    FeatureCategory("gas_stove", 'ガスコンロ', ('ガスコンロ', 'ガスコンロ（2口）', 'ガス', '２口ガスコンロ', 'ガスコンロ（3口）', '３口ガスコンロ',), "facility", "appliance"),
    FeatureCategory("hair_dryer", 'ドライヤー', ('ドライヤー',), "facility", "appliance"),
    FeatureCategory("ih_stove", '電化(IH)コンロ', ('電化(IH)コンロ', 'IH', '２口IHコンロ',), "facility", "appliance"),
    FeatureCategory("kettle", '電気ケトル', ('電気ケトル', 'ポット',), "facility", "appliance"),
    FeatureCategory("lighting", 'デスクランプ・フロアランプ', ('デスクランプ・フロアランプ',), "facility", "appliance"),
    FeatureCategory("microwave", '電子レンジ', ('電子レンジ',), "facility", "appliance"),
    FeatureCategory("refrigerator", '冷蔵庫', ('2ドア冷蔵庫', '冷蔵庫', 'ミニ冷蔵庫',), "facility", "appliance"),
    FeatureCategory("rice_cooker", '炊飯器', ('炊飯器',), "facility", "appliance"),
    FeatureCategory("television", 'テレビ', ('テレビ', 'テレビ(24型)', 'テレビ(32型)', 'スマートTV', 'スマートTV40インチ', 'テレビ(40型)', 'テレビ(50型)',), "facility", "appliance"),
    FeatureCategory("vacuum_cleaner", '掃除機', ('掃除機',), "facility", "appliance"),
    FeatureCategory("washing_machine", '洗濯機', ('室内洗濯機', '洗濯機', '室外洗濯機', 'ドラム式洗濯機',), "facility", "appliance"),
    # --- facility / furniture ---
    FeatureCategory("bed", 'ベッド', ('シングルベッド', 'セミダブルベッド', 'ベッド', 'ダブルベッド', 'ツインベッド', 'セミシングルベッド', 'トゥルースリーパー', 'セミダブルマットレス（シモンズ）', '収納型セミシングルベッド', 'セミダブルベッド（110cm）', '２ダブルベッド', '２ツインベッド',), "facility", "furniture"),
    FeatureCategory("chair", '椅子', ('椅子', 'ダイニングチェア', '座椅子', 'スツール', 'オットマン',), "facility", "furniture"),
    FeatureCategory("mirror", '姿見鏡', ('姿見鏡', 'スタンドミラー',), "facility", "furniture"),
    FeatureCategory("rug", 'ラグマット', ('ラグマット',), "facility", "furniture"),
    FeatureCategory("sofa", 'ソファー（一人掛け）', ('ソファー（一人掛け）', 'ソファー（二人掛け）', '2人掛けソファー', '1人掛けソファー', 'ソファー（三人掛け）',), "facility", "furniture"),
    FeatureCategory("storage_furniture", 'クローゼット', ('クローゼット', 'シューズボックス', 'ハンガーラック', 'ドレッサー',), "facility", "furniture"),
    FeatureCategory("table", '机', ('机', 'テレビ台', 'TV台', 'デスクセット', 'ローテーブル', 'ベッドサイドテーブル', 'テーブル', 'ダイニングテーブル', 'サイドテーブル', 'レンジ台',), "facility", "furniture"),
    # --- facility / room ---
    FeatureCategory("aircon", 'エアコン', ('エアコン', '冷暖房完備',), "facility", "room"),
    FeatureCategory("bath_reheat", '追い炊き', ('追い炊き',), "facility", "room"),
    FeatureCategory("bathroom", '浴室', ('シャワー', '浴室', '3点ユニットバス', 'マイクロバブルシャワーヘッド', 'シャワールーム', '２点ユニット（バス・トイレ）',), "facility", "room"),
    FeatureCategory("bathroom_dryer", '浴室乾燥機', ('浴室乾燥機',), "facility", "room"),
    FeatureCategory("dressing_area", '脱衣所', ('脱衣所',), "facility", "room"),
    FeatureCategory("flooring", 'フローリング', ('フローリング',), "facility", "room"),
    FeatureCategory("hot_water_supply", '給湯設備', ('給湯設備',), "facility", "room"),
    FeatureCategory("independent_washstand", '独立洗面台', ('独立洗面台',), "facility", "room"),
    FeatureCategory("kitchen", 'キッチン', ('キッチン', 'システムキッチン',), "facility", "room"),
    FeatureCategory("loft", 'ロフト', ('ロフト',), "facility", "room"),
    FeatureCategory("separate_bath_toilet", 'バストイレ別', ('バストイレ別', 'セパレート', '浴室トイレセパレート',), "facility", "room"),
    FeatureCategory("storage", '収納', ('収納',), "facility", "room"),
    FeatureCategory("toilet", 'トイレ', ('トイレ',), "facility", "room"),
    FeatureCategory("washlet", 'ウォシュレット', ('ウォシュレット', '温水洗浄便座', '洗浄便座',), "facility", "room"),
    # --- facility / building ---
    FeatureCategory("bicycle_parking.fee_free", '駐輪可（無料）', ('駐輪可（無料）', '駐輪場 無料',), "facility", "building"),
    FeatureCategory("bicycle_parking.fee_negotiable", '駐輪場 要相談', ('駐輪場 要相談',), "facility", "building"),
    FeatureCategory("bicycle_parking.fee_paid", '駐輪可（有料）', ('駐輪可（有料）', '駐輪場 有料',), "facility", "building"),
    FeatureCategory("parking.fee_free", '駐車場 無料', ('駐車場 無料',), "facility", "building"),
    FeatureCategory("parking.fee_negotiable", '駐車場 要相談', ('駐車場 要相談',), "facility", "building"),
    FeatureCategory("motorcycle_parking.fee_free", 'バイク置き場 無料', ('バイク置き場 無料',), "facility", "building"),
    FeatureCategory("motorcycle_parking.fee_negotiable", 'バイク置き場 要相談', ('バイク置き場 要相談',), "facility", "building"),
    FeatureCategory("motorcycle_parking.fee_paid", 'バイク置き場 有料', ('バイク置き場 有料',), "facility", "building"),
    FeatureCategory("internet.fee_free", 'インターネット無料', ('インターネット無料', 'インターネット(無料)',), "facility", "building"),
    FeatureCategory("wifi_rental.fee_paid", 'モバイルWi-Fiルーター（有料）', ('モバイルWi-Fiルーター（有料）', 'Wi-Fiレンタル',), "facility", "building"),
    FeatureCategory("auto_lock", 'オートロック', ('オートロック', 'オートロック（夜間のみ）',), "facility", "building"),
    FeatureCategory("balcony", 'ベランダ', ('ベランダ',), "facility", "building"),
    FeatureCategory("coin_laundry", 'コインランドリー', ('コインランドリー',), "facility", "building"),
    FeatureCategory("delivery_box", '宅配ボックス', ('宅配ボックス', '宅配ＢＯＸ',), "facility", "building"),
    FeatureCategory("elevator", 'エレベーター', ('エレベーター',), "facility", "building"),
    FeatureCategory("garbage_station", 'ゴミ置き場（建物内）', ('ゴミ置き場（建物内）', 'ゴミ置き場（建物外）',), "facility", "building"),
    FeatureCategory("video_intercom", 'モニター付きインターフォン', ('モニター付きインターフォン', 'モニター付きインターホン',), "facility", "building"),
    # --- facility / amenity ---
    FeatureCategory("ashtray", '灰皿', ('灰皿',), "facility", "amenity"),
    FeatureCategory("bedding_set", '寝具一式', ('寝具一式',), "facility", "amenity"),
    FeatureCategory("clothes_hanger", 'ハンガー', ('ハンガー', 'スカートハンガー',), "facility", "amenity"),
    FeatureCategory("curtain", 'カーテン', ('カーテン',), "facility", "amenity"),
    FeatureCategory("daily_supplies", '生活用品あり', ('生活用品あり',), "facility", "amenity"),
    FeatureCategory("drying_rod", '物干し竿', ('物干し竿',), "facility", "amenity"),
    FeatureCategory("shoe_horn", '靴ベラ', ('靴ベラ',), "facility", "amenity"),
    FeatureCategory("slippers", 'スリッパ', ('スリッパ',), "facility", "amenity"),
    FeatureCategory("toilet_supplies", 'トイレットペーパー', ('トイレットペーパー', 'トイレ用ブラシ',), "facility", "amenity"),
    FeatureCategory("trash_can", 'ゴミ箱', ('ゴミ箱',), "facility", "amenity"),
    # --- condition / - ---
    FeatureCategory("corner_room", '角部屋', ('角部屋',), "condition", None),
    FeatureCategory("female_oriented", '女性向け', ('女性向け',), "condition", None),
    FeatureCategory("floor_2plus", '2階以上', ('2階以上',), "condition", None),
    FeatureCategory("foreigner_friendly", '外国人可', ('外国人可', '外国人歓迎',), "condition", None),
    FeatureCategory("furnished", '家具家電付き', ('家具家電付き',), "condition", None),
    FeatureCategory("infants_allowed", '幼児可', ('幼児可',), "condition", None),
    FeatureCategory("near_convenience_store", 'コンビニ至近', ('コンビニ至近',), "condition", None),
    FeatureCategory("near_supermarket", 'スーパー至近', ('スーパー至近',), "condition", None),
    FeatureCategory("no_smoking", '禁煙', ('禁煙',), "condition", None),
    FeatureCategory("pets_allowed", 'ペット可', ('ペット可',), "condition", None),
    FeatureCategory("relatively_new", '築浅5年', ('築浅5年', '築浅3年', '築浅1年',), "condition", None),
    FeatureCategory("south_facing", '南向き', ('南向き',), "condition", None),
    FeatureCategory("top_floor", '最上階', ('最上階',), "condition", None),
    # --- contract / - ---
    FeatureCategory("long_term_discount", '長期割引あり', ('長期割引あり',), "contract", None),
    FeatureCategory("no_utilities", '水道光熱費不要', ('水道光熱費不要',), "contract", None),
    FeatureCategory("prepaid_utility", 'プリペイ給湯・給水システム', ('プリペイ給湯・給水システム', 'プリペイ給湯システム',), "contract", None),
    FeatureCategory("web_application", '来店不要 WEB申込', ('来店不要 WEB申込',), "contract", None),
    FeatureCategory("zero_initial_cost", '敷金礼金仲介料・更新料 ￥0', ('敷金礼金仲介料・更新料 ￥0',), "contract", None),)

# 親 code(束ね・include なし)→ 子 code(複合)対応(決定 18 の導出テーブル)。
# 親・横断 code は FeatureCategory を持たない(判定・配信はこの表から導出する)。
PARENT_CODES: dict[str, tuple[str, ...]] = {
    "bicycle_parking": ("bicycle_parking.fee_free", "bicycle_parking.fee_negotiable", "bicycle_parking.fee_paid",),
    "parking": ("parking.fee_free", "parking.fee_negotiable",),
    "motorcycle_parking": ("motorcycle_parking.fee_free", "motorcycle_parking.fee_negotiable", "motorcycle_parking.fee_paid",),
    "internet": ("internet.fee_free",),
    "wifi_rental": ("wifi_rental.fee_paid",),}

# 旧 code → 現行 code(決定 19)。code の改名・マージ時に登録し、
# required_features への旧 code 指定を現行 code へ丸める(寛容受入と同一機構)。
CODE_ALIASES: dict[str, str] = {}

# フィルタ対象外語彙(決定 15)。差分検知の母集団から除外する。
NON_FILTER_FEATURES: frozenset[str] = frozenset({
    '360度パノラマ画像',
    'くつろぎstyle',
    'Luxury style',
    # bratto サイト側の入力ミス(パーサ故障ではない・2026-10-08 ユーザー調査で
    # 確定)。サイト入力異常の実例として設計書 §7-2 に記録する。
    'ハンガーラック\u3000茶碗\u3000汁椀\u3000箸\u3000マグカップ\u3000コップ\u3000平皿\u3000スプーン\u3000フォーク \u3000おたま\u3000フライ返し\u3000ボウル\u3000ザル\u3000三角コーナー\u3000まな板\u3000包丁\u3000食器用洗剤 スポンジ\u3000洗濯用洗剤\u3000シャンプー\u3000リンス\u3000ボディソープ',})


def normalize_feature_name(name: str) -> str:
    """辞書突合のための入力正規化(strip + NFKC + casefold・§7-7)。"""
    return unicodedata.normalize("NFKC", name).strip().casefold()


def cross_codes() -> tuple[str, ...]:
    """横断 code(修飾語)の全集合 — 複合 code の接尾辞から導出(構造不変条件 d)。"""
    return tuple(sorted({c.split(".", 1)[1] for c in _BY_CODE if "." in c}))


_BY_CODE: dict[str, FeatureCategory] = {c.code: c for c in FEATURE_CATEGORIES}
# 正規化生値 → code のルックアップ表(生名→code 一意・決定 18)
_INCLUDE_INDEX: dict[str, str] = {
    normalize_feature_name(name): cat.code
    for cat in FEATURE_CATEGORIES
    for name in cat.include
}
_NON_FILTER_INDEX: frozenset[str] = frozenset(
    normalize_feature_name(n) for n in NON_FILTER_FEATURES
)


def lookup_feature_category(raw_name: str) -> FeatureCategory | None:
    """DB 生値 → この語彙の属するカテゴリ(未知語は None)。両辺正規化で突合。"""
    code = _INCLUDE_INDEX.get(normalize_feature_name(raw_name))
    return _BY_CODE[code] if code is not None else None


def is_non_filter(raw_name: str) -> bool:
    """語彙がフィルタ対象外(ignore)か(両辺正規化で突合)。"""
    return normalize_feature_name(raw_name) in _NON_FILTER_INDEX


def feature_unit_codes() -> tuple[str, ...]:
    """feature 単位 code(単純 + 複合)の全集合。親・横断 code は含まない。"""
    return tuple(_BY_CODE)


def format_categories_docstring() -> str:
    """MCP docstring 用のカテゴリ一覧を生成する(設計 §3.5・group 構造付き)。

    facility は sub 併記。複合 code は通常行に含み、親 code(束ね)と
    横断 code(佃用可)は末尾に別ブロックで併記する。
    """
    lines: list[str] = []
    for group in ("facility", "condition", "contract", "other"):
        cats = [c for c in FEATURE_CATEGORIES if c.group == group]
        if not cats:
            continue
        if group == "facility":
            for sub in ("appliance", "furniture", "room", "building", "amenity"):
                sub_cats = [c for c in cats if c.sub == sub]
                if sub_cats:
                    lines.append(
                        f"- facility/{sub}: "
                        + ", ".join(f"{c.code}({c.label})" for c in sub_cats)
                    )
        else:
            lines.append(f"- {group}: " + ", ".join(f"{c.code}({c.label})" for c in cats))

    lines.append(
        "- 親 code(束ね・子 code 全体の OR): "
        + ", ".join(
            f"{p}[{', '.join(c.rsplit('.', 1)[1] for c in children)}]"
            for p, children in PARENT_CODES.items()
        )
    )
    lines.append("- 横断 code(佃用可・「何かの費用X」): " + ", ".join(cross_codes()))
    return "\n".join(lines)
