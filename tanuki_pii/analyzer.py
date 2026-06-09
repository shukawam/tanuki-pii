"""Presidio AnalyzerEngine の構築とラッパ。

- NLP エンジン: SpacyNlpEngine（ja_core_news_sm はトークナイズ専用、en_core_web_lg は英語NER）
- 日本語 NER: BERT（JapaneseBertRecognizer, ja）
- 日本語構造化 PII: 正規表現 Recognizer（ja/en 両登録）
- 言語非依存パターン: Presidio 既定（Email/CreditCard/IP/...）
- 認証情報: PasswordRecognizer（ja/en）
ja の spaCy NER は登録しない（BERT に任せ、二重検出を防ぐ）。
"""

import logging

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from .config import settings
from .mappings import SUPPORTED_LANGS
from .password_recognizer import PasswordRecognizer
from .recognizers import register_japanese_recognizers
from .recognizers.bert import JapaneseBertRecognizer
from .recognizers.custom import build_ad_hoc_recognizers

logger = logging.getLogger("analyzer")

# 「Entity X doesn't have the corresponding recognizer in language: en」等の
# 無害な警告を抑制（多言語エンティティを en でも要求するため大量に出る）。
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

_LANGS = ["ja", "en"]

# 言語に依存しない（locale 前提を持たない）既定 Recognizer。両言語に揃える。
_LANGUAGE_INDEPENDENT = (
    "CreditCardRecognizer",
    "CryptoRecognizer",
    "EmailRecognizer",
    "IbanRecognizer",
    "IpRecognizer",
    "MacAddressRecognizer",
    "UrlRecognizer",
    "PhoneRecognizer",
    "DateRecognizer",
)


def _ensure_language_independent_parity(registry):
    """言語非依存 Recognizer を全 _LANGS に存在させる（不足分を複製登録）。"""
    have = {
        (type(r).__name__, getattr(r, "supported_language", None))
        for r in registry.recognizers
    }
    # 各クラスの既存インスタンスを雛形にして、不足言語へ複製する。
    by_name = {}
    for r in registry.recognizers:
        by_name.setdefault(type(r).__name__, r)
    for name in _LANGUAGE_INDEPENDENT:
        template = by_name.get(name)
        if template is None:
            continue
        cls = type(template)
        for lang in _LANGS:
            if (name, lang) not in have:
                try:
                    registry.add_recognizer(cls(supported_language=lang))
                except Exception as e:  # pragma: no cover
                    logger.warning("could not add %s for %s: %s", name, lang, e)


def build_analyzer_engine():
    nlp_engine = SpacyNlpEngine(
        models=[
            {"lang_code": "ja", "model_name": settings.spacy_ja_model},
            {"lang_code": "en", "model_name": settings.spacy_en_model},
        ]
    )
    nlp_engine.load()

    registry = RecognizerRegistry(supported_languages=_LANGS)
    registry.load_predefined_recognizers(languages=_LANGS, nlp_engine=nlp_engine)

    # ja の spaCy NER を抑止（BERT に任せる）。
    registry.recognizers = [
        r
        for r in registry.recognizers
        if not (isinstance(r, SpacyRecognizer) and getattr(r, "supported_language", None) == "ja")
    ]

    # 言語非依存の Presidio 既定 Recognizer の言語間パリティを保証する。
    # Presidio の load_predefined_recognizers は一部（例: CreditCard）を en にしか
    # 登録しないため、ja でも検出できるよう不足分を補う。
    _ensure_language_independent_parity(registry)

    # 日本語固有の正規表現 Recognizer（ja/en 両方）。
    register_japanese_recognizers(registry, _LANGS)

    # 認証情報。
    for lang in _LANGS:
        pw = PasswordRecognizer(lang)
        pw.supported_language = lang
        registry.add_recognizer(pw)

    # 日本語 BERT NER（ja のみ）。
    if settings.jp_use_bert:
        bert = JapaneseBertRecognizer(
            model_name=settings.jp_bert_model,
            score_threshold=settings.jp_ner_score_threshold,
            max_chars=settings.bert_max_chars,
            concurrency=settings.bert_concurrency,
            language="ja",
        )
        registry.add_recognizer(bert)

    engine = AnalyzerEngine(
        nlp_engine=nlp_engine,
        registry=registry,
        supported_languages=_LANGS,
    )

    # PasswordRecognizer が doc.sents を使うため sentencizer を確保。
    for lang in _LANGS:
        nlp = nlp_engine.nlp[lang]
        if "parser" not in nlp.pipe_names and "senter" not in nlp.pipe_names \
                and "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")

    return engine


class PiiAnalyzer:
    """pii.py が使う解析インターフェース。

    analyze(text, entities, language, custom_patterns) -> List[RecognizerResult]
    custom_patterns は呼び出しごとに ad-hoc Recognizer として隔離注入する。
    """

    def __init__(self, engine=None):
        self._engine = engine or build_analyzer_engine()

    @property
    def supported_languages(self):
        return list(SUPPORTED_LANGS)

    def warmup(self):
        """BERT 等の遅延ロードを起動時に済ませる。"""
        try:
            self._engine.analyze(text="ウォームアップ", entities=None, language="ja")
        except Exception as e:  # pragma: no cover
            logger.warning("warmup failed: %s", e)

    def analyze(self, text, entities, language, custom_patterns=None):
        ad_hoc = build_ad_hoc_recognizers(custom_patterns or [], language)
        return self._engine.analyze(
            text=text,
            entities=entities,
            language=language,
            ad_hoc_recognizers=ad_hoc or None,
            return_decision_process=False,
        )
