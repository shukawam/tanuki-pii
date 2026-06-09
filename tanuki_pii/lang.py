"""言語判定とロケール解決。

設計（プラン §公式差分#3 / #3b）:
- detected_language（レスポンス用）: 公式 detect_language と同一。
  検出値が SUPPORTED_LANGS なら採用、zh-cn/zh-tw→zh、非対応は "en" に丸め。
  detect() が例外を投げた場合は呼び出し側で "unknown" を使う。
- analyzer_language（Presidio に渡す内部言語）: script heuristic で決定。
  日本語文字（ひらがな/カタカナ/漢字）を含めば "ja"、含まなければ detected の丸め結果。
  → 数字のみ/英字混じりで langdetect が ja を返さなくても BERT(ja) を起動できる。
"""

import re

from langdetect import detect

from .mappings import SUPPORTED_LANGS

# 日本語文字（ひらがな・カタカナ・CJK統合漢字・全角記号の一部）。
_JP_CHAR_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
# 英語フォールバック起動判定: 大文字始まりの固有名詞候補（人名・組織名等）。
# メールアドレスやドメインの小文字 latin 片では起動しないようにする。
_LATIN_NAME_RE = re.compile(r"[A-Z][A-Za-z]+")

# Faker のロケール対応表（プラン §synthetic）。
LOCALE_MAP = {"ja": "ja_JP", "en": "en_US"}

UNKNOWN = "unknown"


def contains_japanese(text: str) -> bool:
    return bool(_JP_CHAR_RE.search(text))


# 大文字始まりの語が空白/ハイフン/アポストロフィで連なる固有名詞候補。
_LATIN_NAME_SEQ_RE = re.compile(r"[A-Z][A-Za-z]+(?:[ '\-][A-Z][A-Za-z]+)*")


def contains_latin_words(text: str) -> bool:
    """英語 NER パスを起動すべきか（大文字始まりの固有名詞候補があるか）。"""
    return bool(_LATIN_NAME_RE.search(text))


def iter_latin_name_segments(text: str):
    """ラテン固有名詞候補のセグメントを (segment_text, offset) で返す。

    混在文で英語 NER を日本語部分に適用しないよう、ラテン片だけを抽出する。
    """
    for m in _LATIN_NAME_SEQ_RE.finditer(text):
        yield m.group(0), m.start()


def detect_language(text: str) -> str:
    """公式 detect_language 互換。非対応言語は 'en' に丸める。

    detect() が例外を投げる場合（純記号・空白等）は呼び出し側で捕捉して 'unknown' にする。
    """
    lang_code = detect(text)
    if lang_code in ("zh-cn", "zh-tw"):
        lang_code = "zh"
    return lang_code if lang_code in SUPPORTED_LANGS else "en"


def resolve_analyzer_language(text: str, detected_language: str) -> str:
    """Presidio に渡す言語を決める。

    detected_language が 'unknown'（detect 例外）でも、日本語文字があれば ja、
    なければ en にフォールバックして構造化 Recognizer は走らせる。
    """
    if contains_japanese(text):
        return "ja"
    if detected_language in SUPPORTED_LANGS:
        return detected_language
    return "en"


def faker_locale(language: str) -> str:
    return LOCALE_MAP.get(language, "en_US")
