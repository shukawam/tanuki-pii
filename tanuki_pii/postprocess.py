"""検出結果の後処理（重複排除・内包除去・マージ展開）。

公式 server.py の remove_duplicated_span / remove_subspan / find_all_indexes /
get_analyzer_results を再現する。加えて、日本語の構造化 PII（正規表現由来）が
広い NER スパンに飲み込まれないよう保護する（プラン §統合の優先順位）。

start/end ベースで実装し、presidio に依存せず単体テスト可能にしている。
入力 result は .start / .end / .entity_type / .score を持つオブジェクト。
"""

from .mappings import (
    CUSTOM_ENTITY,
    JP_ADDRESS,
    JP_BANK_ACCOUNT,
    JP_CORPORATE_NUMBER,
    JP_DATE_WAREKI,
    JP_DRIVERS_LICENSE,
    JP_HEALTH_INSURANCE,
    JP_MY_NUMBER,
    JP_PASSPORT,
    JP_POSTAL_CODE,
    NER_ENTITIES,
    PASSWORD_ENTITY,
)

# 構造化 PII（正規表現由来）。NER スパンより優先して保護する。
STRUCTURED_PRIORITY = {
    JP_MY_NUMBER,
    JP_CORPORATE_NUMBER,
    JP_POSTAL_CODE,
    JP_ADDRESS,
    JP_DRIVERS_LICENSE,
    JP_HEALTH_INSURANCE,
    JP_PASSPORT,
    JP_BANK_ACCOUNT,
    JP_DATE_WAREKI,
    CUSTOM_ENTITY,
    PASSWORD_ENTITY,
}


def _contained_in(inner, outer) -> bool:
    """inner が outer に内包される（端の一致を含む）。"""
    return inner.start >= outer.start and inner.end <= outer.end


def _contains(outer, inner) -> bool:
    return outer.start <= inner.start and outer.end >= inner.end


def remove_duplicated_span(results):
    """同一スパンは最高スコアのみ残す（公式 remove_duplicated_span 互換）。"""
    filtered = {}
    for result in results:
        key = "%s:%s" % (result.start, result.end)
        existed = filtered.get(key)
        if existed is None:
            filtered[key] = result
            continue
        if result.score > existed.score:
            filtered[key] = result
    return list(filtered.values())


def remove_subspan(results):
    """内包スパンを除去する。

    非構造化（NER等）は公式 remove_subspan を忠実に再現（ORGANIZATION を後処理）。
    構造化 PII は必ず残し、それに内包される非構造化スパンを除去する（飲み込み防止）。
    英語など構造化 PII を含まない入力では公式と同一挙動になる。
    """
    structured = [r for r in results if r.entity_type in STRUCTURED_PRIORITY]
    rest = [r for r in results if r.entity_type not in STRUCTURED_PRIORITY]

    # --- 公式アルゴリズム（非構造化） ---
    rest = sorted(rest, key=lambda x: -(x.end - x.start))
    filtered = []
    orgs = []
    for result in rest:
        if result.entity_type == "ORGANIZATION":
            orgs.append(result)
            continue
        to_keep = True
        for kept in filtered:
            if _contained_in(result, kept):
                to_keep = False
                break
        if to_keep:
            filtered.append(result)

    for org in orgs:
        to_keep = True
        for result in filtered:
            if _contained_in(org, result) or _contains(org, result):
                to_keep = False
                break
        if to_keep:
            filtered.append(org)

    # --- 構造化 PII を保護（NER スパンに内包されても残す） ---
    # ただし、より強い非NERパターン（例: PHONE_NUMBER）に内包される弱い構造化
    # （例: 郵便番号の誤検知）は、その強パターンを優先して落とす。
    if structured:
        kept_structured = []
        for s in structured:
            swallowed = any(
                _contained_in(s, r)
                and r.entity_type not in NER_ENTITIES
                and r.score > s.score
                for r in filtered
            )
            if not swallowed:
                kept_structured.append(s)
        # 残った構造化 PII に内包される非構造化スパンを除去。
        filtered = [
            r
            for r in filtered
            if not any(_contained_in(r, s) for s in kept_structured)
        ]
        filtered.extend(kept_structured)

    return filtered


def find_all_indexes(main_string, substring):
    """main_string 中の substring の全出現開始位置（公式 find_all_indexes 互換）。"""
    indices = []
    if not substring:
        return indices
    start_index = 0
    while True:
        start_index = main_string.find(substring, start_index)
        if start_index == -1:
            break
        indices.append(start_index)
        start_index += 1
    return indices


def get_analyzer_results(text, anonymized_items, op_map, lang):
    """匿名化対象の結果から analyzer_results を構築（公式 get_analyzer_results 互換）。

    op_map に残ったマージエンティティ（複数語が1つの置換にまとめられたもの）は
    find_all_indexes で全位置に展開する。
    """
    results = []
    found = {}
    for item in anonymized_items:
        origin = item["original_text"]
        mapped = op_map.get(origin)
        redact = mapped[0] if mapped else None
        if redact:
            results.append(
                {
                    "start": item["start"],
                    "end": item["end"],
                    "detected_language": lang,
                    "original_text": origin,
                    "redact_text": redact,
                    "entity_type": op_map[origin][1],
                }
            )
            found.setdefault(origin, True)

    for origin, (redact, et) in op_map.items():
        if found.get(origin):
            continue
        for idx in find_all_indexes(text, origin):
            results.append(
                {
                    "start": idx,
                    "end": idx + len(origin),
                    "detected_language": lang,
                    "original_text": origin,
                    "redact_text": redact,
                    "entity_type": et,
                }
            )

    return sorted(results, key=lambda x: x["start"])
