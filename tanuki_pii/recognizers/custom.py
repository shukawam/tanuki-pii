"""per-request の custom_patterns を ad-hoc Recognizer として生成する。

公式は global registry に追加するバグがあるが、本サービスは呼び出しごとに隔離する。
ReDoS 対策として `regex` ライブラリの timeout 機能でマッチを打ち切る。
"""

import logging

import regex
from presidio_analyzer import EntityRecognizer, RecognizerResult

from ..config import settings
from ..mappings import CUSTOM_ENTITY

logger = logging.getLogger("CustomRegexRecognizer")


class CustomRegexRecognizer(EntityRecognizer):
    """ユーザ提供の regex を timeout 付きで実行する Recognizer。"""

    def __init__(self, patterns, language):
        super().__init__(
            supported_entities=[CUSTOM_ENTITY],
            supported_language=language,
            name="CustomRegexRecognizer",
        )
        self._compiled = []
        for p in patterns:
            try:
                self._compiled.append((regex.compile(p["regex"]), float(p["score"])))
            except regex.error as e:
                logger.warning("Skip invalid custom regex %r: %s", p.get("name"), e)

    def load(self):
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if CUSTOM_ENTITY not in entities:
            return []
        results = []
        for compiled, score in self._compiled:
            try:
                for m in compiled.finditer(
                    text, timeout=settings.custom_pattern_regex_timeout
                ):
                    if m.start() == m.end():
                        continue
                    results.append(
                        RecognizerResult(
                            entity_type=CUSTOM_ENTITY,
                            start=m.start(),
                            end=m.end(),
                            score=score,
                        )
                    )
            except TimeoutError:
                logger.warning("custom regex timed out; skipping")
        return results


def build_ad_hoc_recognizers(custom_patterns, language):
    """custom_patterns から ad-hoc Recognizer を生成（無ければ空リスト）。

    呼び出し時の analyzer_language に合わせて supported_language を設定する。
    """
    if not custom_patterns:
        return []
    if len(custom_patterns) > settings.custom_pattern_max_count:
        custom_patterns = custom_patterns[: settings.custom_pattern_max_count]
    return [CustomRegexRecognizer(custom_patterns, language)]
