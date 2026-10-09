"""search_text 合成 (Phase 7a: pgvector 意味検索の embedding 入力).

設計正本: docs/sqlite-pg-migration-plan.md Phase 7 (E7: gemini-embedding-2・3072 次元)。

properties 本体 + 子テーブル (features / accesses / price_plans / campaigns) から
日本語の自然文を合成し、property_embeddings.search_text に保存する。保存理由は
「何をベクトル化したか」の追跡性と、内容変化 (search_text_hash 不一致) による
差分再生成の対象とするため。

設計根拠
--------
- **2000 字キャップ (= SEARCH_TEXT_CAP)**: gemini-embedding-2 の入力上限は
  8,192 token。本番実測の最悪合成 (point_text max 1,275 字 + features 37 件) でも
  ~2,400 字 ≒ 保守見積 2 token/字で ~4,800 token と上限に届かないが、想定外の
  長大入力 (サイト側の入力ミス等) で API エラーが恒久失敗するのを防ぐため、
  合成関数側で 2,000 字にキャップする。超過時は**セクション単位で優先度の低い
  ものから省略**し、途中切断はしない (意味の分断ベクトルを避ける)。
  優先度 (高い順): ①タイトル/所在地/間取り等の属性 ②point_text ③アクセス
  ④賃料プラン ⑤キャンペーン ⑥設備。①はいかなる場合も省略しない
  (実データでは 100 字未満のため、①のみで超過するのはデータ破損相当)。
- **チャンク分割不採用**: 意味検索の単位は物件プロファイル全体 (1 物件 = 1 ベクトル)
  であり、分割はベクトルを分散させて検索品質を損なう。キャップで入力上限を
  原理的に担保できるため分割は行わない。

列の実定義は src/alembic/versions/0001_pg_baseline.py (properties /
property_accesses / price_plans / campaigns)。欠損列 (None・空文字) はその句を
省略し、文字列 "None" が出力へ混入しないことを保証する。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# 入力上限 8,192 token への保険 (根拠はモジュール docstring)。
SEARCH_TEXT_CAP = 2000

# 非対称検索のドキュメント側プロンプト指示 (docs/embedding-batch-api-plan.md §4-4)。
# gemini-embedding-2 は taskType が no-op のため、ドキュメント準拠の接頭辞で
# 格納用embeddingの意図を伝える。query 側は store.embeddings.QUERY_PREFIX。
DOCUMENT_PREFIX = "text: "

# 改行・タブ・全角空白を含む連続空白の正規化用 (point_text 等の説明文向け)。
_WHITESPACE_RE = re.compile(r"[\s\u3000]+")


def _clean(value: Any) -> str | None:
    """DB 値を表示用テキストへ正規化する。欠損 (None・空・空白のみ) は None。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_text(value: Any) -> str | None:
    """整数として整形可能な値のみ文字列化 (築年・階数・徒歩分など)。"""
    text = _clean(value)
    if text is None:
        return None
    try:
        return str(int(float(text)))
    except ValueError:
        return None


def _money_text(value: Any) -> str | None:
    """金額を桁区切り付きで整形 (4500 -> "4,500")。欠損・非数値は None。"""
    text = _clean(value)
    if text is None:
        return None
    try:
        return f"{int(float(text)):,}"
    except ValueError:
        return None


def _normalize_text(value: Any) -> str | None:
    """説明文 (point_text / raw_text 等) の改行・連続空白を単一スペースへ正規化。"""
    text = _clean(value)
    if text is None:
        return None
    normalized = _WHITESPACE_RE.sub(" ", text).strip()
    return normalized or None


# ---------------------------------------------------------------------------
# セクション構築 (優先度 ①〜⑥)
# ---------------------------------------------------------------------------

def _area_text(prop: dict) -> str | None:
    """専有面積。max のみの物件は「最大N㎡」、範囲なら「N〜M㎡」。"""
    area = _clean(prop.get("area_m2"))
    area_max = _clean(prop.get("area_m2_max"))
    if area and area_max:
        return f"{area}〜{area_max}㎡"
    if area:
        return f"{area}㎡"
    if area_max:
        return f"最大{area_max}㎡"
    return None


def _attribute_clauses(prop: dict) -> list[str]:
    """属性節のリスト (間取り/面積/築年/構造/階/向き/定員)。欠損節は省略。"""
    clauses: list[str] = []
    layout = _clean(prop.get("layout"))
    if layout:
        clauses.append(f"間取りは{layout}")
    area = _area_text(prop)
    if area:
        clauses.append(f"専有面積は{area}")
    built_year = _int_text(prop.get("built_year"))
    if built_year:
        clauses.append(f"築{built_year}年")
    structure = _clean(prop.get("structure"))
    if structure:
        clauses.append(structure)
    floor_number = _int_text(prop.get("floor_number"))
    if floor_number:
        clauses.append(f"{floor_number}階")
    orientation = _clean(prop.get("orientation_text"))
    if orientation:
        # "南" -> "南向き"。"南向き" 等の語尾重複はしない。
        clauses.append(orientation if orientation.endswith("向き") else f"{orientation}向き")
    capacity = _clean(prop.get("capacity_text"))
    if capacity:
        clauses.append(f"定員{capacity}")
    return clauses


def _head_section(prop: dict) -> str:
    """優先度 ①: タイトル + 所在地 + 属性の一文ブロック (省略しない)。"""
    sentences: list[str] = []
    title = _clean(prop.get("title"))
    if title:
        sentences.append(title if title.endswith("。") else f"{title}。")
    location = "".join(
        part
        for part in (
            _clean(prop.get("prefecture_name")),
            _clean(prop.get("municipality")),
            _clean(prop.get("address")),
        )
        if part
    )
    if location:
        sentences.append(f"{location}にあるマンスリーマンション。")
    clauses = _attribute_clauses(prop)
    if clauses:
        sentences.append("、".join(clauses) + "。")
    return "".join(sentences)


def _access_items(accesses: list[dict]) -> list[str]:
    """優先度 ③ の要素。「{line_name} {station_name}駅 徒歩{walk_minutes}分」。"""
    items: list[str] = []
    for access in accesses or []:
        line = _clean(access.get("line_name"))
        station = _clean(access.get("station_name"))
        walk = _int_text(access.get("walk_minutes"))
        head = " ".join(part for part in (line, station) if part)
        if station and not station.endswith("駅"):
            head = f"{head}駅"
        parts = [part for part in (head, f"徒歩{walk}分" if walk else None) if part]
        if parts:
            items.append(" ".join(parts))
            continue
        raw = _normalize_text(access.get("raw_text"))
        if raw:
            items.append(raw)
    return items


def _plan_items(plans: list[dict]) -> list[str]:
    """優先度 ④ の要素。「{plan_name} {rent}円/日 (最短〜最長日数)」。

    賃料は rent_current_yen (現行) を優先し欠損時 rent_original_yen へ
    フォールバック。金額も日数も無い生プランは raw_text を使う。
    """
    items: list[str] = []
    for plan in plans or []:
        name = _clean(plan.get("plan_name"))
        rent = plan.get("rent_current_yen")
        if rent is None:
            rent = plan.get("rent_original_yen")
        rent_text = _money_text(rent)
        unit = "円/月" if _clean(plan.get("presentation_unit")) == "per_month" else "円/日"
        min_days = _int_text(plan.get("duration_min_days"))
        max_days = _int_text(plan.get("duration_max_days"))
        if min_days and max_days:
            duration = f"{min_days}〜{max_days}日"
        elif min_days:
            duration = f"{min_days}日〜"
        elif max_days:
            duration = f"〜{max_days}日"
        else:
            duration = None
        parts = [
            part
            for part in (
                name,
                f"{rent_text}{unit}" if rent_text else None,
                f"({duration})" if duration else None,
            )
            if part
        ]
        if parts:
            items.append(" ".join(parts))
            continue
        raw = _normalize_text(plan.get("raw_text"))
        if raw:
            items.append(raw)
    return items


def _campaign_items(campaigns: list[dict]) -> list[str]:
    """優先度 ⑤ の要素。「{title}: {content}」。同一内容の重複は除去。"""
    items: list[str] = []
    seen: set[str] = set()
    for campaign in campaigns or []:
        title = _normalize_text(campaign.get("title"))
        content = _normalize_text(campaign.get("content"))
        text = f"{title}: {content}" if title and content else (title or content)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _feature_items(features: list[str]) -> list[str]:
    """優先度 ⑥ の要素。重複除去 (順序維持)・空文字は除外。"""
    return list(dict.fromkeys(f for f in (str(f).strip() for f in features or []) if f))


# ---------------------------------------------------------------------------
# 合成本体
# ---------------------------------------------------------------------------

def compose_search_text(
    prop: dict,
    features: list[str],
    accesses: list[dict],
    plans: list[dict],
    campaigns: list[dict],
) -> str:
    """物件プロファイルを embedding 入力用の日本語自然文へ合成する。

    セクション優先度 (高い順): ①タイトル/所在地/間取り ②point_text
    ③アクセス ④賃料プラン ⑤キャンペーン ⑥設備。合計が SEARCH_TEXT_CAP
    (2000 字) を超える場合は低優先度のセクションから丸ごと省略する
    (途中切断はしない・①は省略しない)。

    先頭に :data:`DOCUMENT_PREFIX` (``"text: "``) を接頭する。gemini-embedding-2
    は taskType が no-op であることが実測されており (docs/embedding-batch-api-plan.md
    §2-3)、非対称検索はドキュメント準拠のプロンプト指示で行う。接頭辞は
    「ベクトル化したもの」の一部なので search_text に含め (= hash 対象)・
    キャップ予算からも控除する (保存値全体が SEARCH_TEXT_CAP 以内に収まる)。
    """
    sections: list[str] = []
    head = _head_section(prop)
    if head:
        sections.append(head)
    point_text = _normalize_text(prop.get("point_text"))
    if point_text:
        sections.append(point_text)
    access_items = _access_items(accesses)
    if access_items:
        sections.append("アクセス: " + "、".join(access_items))
    plan_items = _plan_items(plans)
    if plan_items:
        sections.append("賃料プラン: " + "、".join(plan_items))
    campaign_items = _campaign_items(campaigns)
    if campaign_items:
        sections.append("キャンペーン: " + "、".join(campaign_items))
    feature_items = _feature_items(features)
    if feature_items:
        sections.append("設備: " + "、".join(feature_items))

    if not sections:
        return ""
    # キャップ: 末尾 (低優先度) からセクション丸ごと省略。① (先頭) は保持。
    # 予算から接頭辞長を控除し、戻り値全体 (prefix + 本文) が SEARCH_TEXT_CAP 以内に収まる。
    budget = SEARCH_TEXT_CAP - len(DOCUMENT_PREFIX)
    while len(sections) > 1 and sum(map(len, sections)) + len(sections) - 1 > budget:
        sections.pop()
    return DOCUMENT_PREFIX + "\n".join(sections)


def search_text_hash(text: str) -> str:
    """search_text の内容ハッシュ (SHA256 hex)。差分再生成の判定に使う。

    schema_meta KV の feature_dict_hash と同型の「内容ハッシュで差分同期」
    慣習 (docs/sqlite-pg-migration-plan.md Phase 7) に合わせる。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
