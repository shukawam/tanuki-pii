"""環境変数ベースの設定。"""

import os


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # BERT 日本語 NER モデル。配布 Docker の既定は MIT ライセンスの tsmatz。
    # jurabi/bert-ner-japanese は CC-BY-SA-3.0 のためオプトイン。
    jp_bert_model: str = os.getenv("JP_BERT_MODEL", "tsmatz/xlm-roberta-ner-japanese")
    # BERT を有効化するか（テスト/軽量起動では無効にできる）。
    jp_use_bert: bool = _bool("JP_USE_BERT", True)
    jp_ner_score_threshold: float = float(os.getenv("JP_NER_SCORE_THRESHOLD", "0.5"))

    # spaCy モデル（トークナイズ用＋英語NER用）。
    spacy_ja_model: str = os.getenv("SPACY_JA_MODEL", "ja_core_news_sm")
    spacy_en_model: str = os.getenv("SPACY_EN_MODEL", "en_core_web_lg")

    # 同時 BERT 推論数の上限（CPU p95 保護）。
    bert_concurrency: int = int(os.getenv("BERT_CONCURRENCY", "1"))
    # BERT chunking のトークン上限（512 制限対策の目安。文字数ベースで近似）。
    bert_max_chars: int = int(os.getenv("BERT_MAX_CHARS", "400"))

    # domain カテゴリを url の別名として受理する（既定は公式互換で 400）。
    enable_domain_alias: bool = _bool("ENABLE_DOMAIN_ALIAS", False)
    # credentials の identified/anonymized を全 message 集約する改善版（既定は公式互換=last-message）。
    credentials_aggregate_all: bool = _bool("CREDENTIALS_AGGREGATE_ALL", False)

    # custom_patterns（ユーザ regex）の入力制限（ReDoS 緩和）。
    custom_pattern_max_regex_len: int = int(os.getenv("CUSTOM_PATTERN_MAX_REGEX_LEN", "1000"))
    custom_pattern_max_count: int = int(os.getenv("CUSTOM_PATTERN_MAX_COUNT", "50"))
    custom_pattern_regex_timeout: float = float(os.getenv("CUSTOM_PATTERN_REGEX_TIMEOUT", "1.0"))
    # 解析対象本文の最大長。
    max_text_length: int = int(os.getenv("MAX_TEXT_LENGTH", "50000"))


settings = Settings()
