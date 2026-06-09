"""日本語 PII Recognizer の登録とカスタムパターン生成。"""

from .japanese import build_japanese_recognizers
from .custom import build_ad_hoc_recognizers

__all__ = ["register_japanese_recognizers", "build_ad_hoc_recognizers"]


def register_japanese_recognizers(registry, languages):
    """日本語固有 Recognizer を指定言語すべてに登録する。

    構造化 PII（電話・マイナンバー等）は言語判定に依存させないため ja/en 両方に登録する。
    """
    for language in languages:
        for recognizer in build_japanese_recognizers(language):
            registry.add_recognizer(recognizer)
