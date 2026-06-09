"""PII 検出・匿名化のコア（公式 do_sanitize_pii / do_sanitize_credentials 互換）。

analyzer は `analyze(text, entities, language, ad_hoc_recognizers=None)` を持つ
オブジェクト（実体は analyzer.PiiAnalyzer。テストでは fake を注入可能）。
"""

import time

from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from .config import settings
from .faker_gen import RedactGenerator, RequestCounters
from .lang import (
    UNKNOWN,
    contains_latin_words,
    detect_language,
    iter_latin_name_segments,
    resolve_analyzer_language,
)
from .mappings import (
    ALL_ANONYMIZERS,
    MASK_LENGTH,
    PASSWORD_ENTITY,
    PASSWORD_REPLACEMENT,
    STRUCTURED_REGEX_ENTITIES,
    get_sorted_anonymize_keys,
)
from .postprocess import (
    get_analyzer_results,
    remove_duplicated_span,
    remove_subspan,
)

_anonymizer = AnonymizerEngine()


def current_milli_time():
    return round(time.time() * 1000)


def _empty_message(text, msg_id, detected_language):
    return {
        "sanitized_text": text,
        "analyzer_results": [],
        "detected_language": detected_language,
        "msg_id": msg_id,
    }


def _analyze_message(analyzer, text, custom_patterns):
    """1メッセージを解析して (detected_language, sorted_results) を返す。

    - detect 例外時(#3b): detected_language="unknown"、NER をスキップし構造化 regex のみ。
    - 混在文(#2): analyzer_language=ja でも en パスを追加実行してマージ。
    """
    try:
        detected_language = detect_language(text)
        detect_failed = False
    except Exception:
        detected_language = UNKNOWN
        detect_failed = True

    analyzer_language = resolve_analyzer_language(text, detected_language)

    if detect_failed:
        # #3b: NER は走らせず、言語非依存の構造化 regex のみ。
        entities = STRUCTURED_REGEX_ENTITIES
        raw = analyzer.analyze(
            text=text,
            entities=entities,
            language=analyzer_language,
            custom_patterns=custom_patterns,
        )
    else:
        raw = analyzer.analyze(
            text=text,
            entities=ALL_ANONYMIZERS,
            language=analyzer_language,
            custom_patterns=custom_patterns,
        )
        # #2: 混在文ではラテン固有名詞セグメントだけを英語 NER にかけてマージ。
        # 日本語部分に英語 NER を適用してスパンが過剰拡張するのを防ぐ。
        if analyzer_language == "ja" and contains_latin_words(text):
            for seg_text, seg_off in iter_latin_name_segments(text):
                seg_results = analyzer.analyze(
                    text=seg_text,
                    entities=ALL_ANONYMIZERS,
                    language="en",
                    custom_patterns=custom_patterns,
                )
                for r in seg_results:
                    r.start += seg_off
                    r.end += seg_off
                    raw.append(r)

    unique = remove_duplicated_span(raw)
    sorted_results = sorted(remove_subspan(unique), key=lambda x: x.start)
    return detected_language, sorted_results


def do_sanitize_pii(data, analyzer):
    """公式 do_sanitize_pii 互換。data は validate_sanitize_request の戻り値。"""
    from .validation import validate_message

    start_time = current_milli_time()
    messages = data["messages"]
    redact_type = data["redact_type"]
    entities_to_anonymize = data["entities_to_anonymize"]
    custom_patterns = data["custom_patterns"]

    identified_pii_set = set()
    anonymized_pii_set = set()
    sanitized_messages = []
    # カウンタはリクエスト単位で継続（公式互換: PLACEHOLDER の採番が message を跨ぐ）。
    counters = RequestCounters()

    for message in messages:
        text, msg_id = validate_message(message)

        if len(text.strip()) == 0:
            sanitized_messages.append(_empty_message(text, msg_id, None))
            continue

        detected_language, sorted_results = _analyze_message(
            analyzer, text, custom_patterns
        )

        identified_pii_set.update(r.entity_type for r in sorted_results)
        results_to_anonymize = [
            r for r in sorted_results if r.entity_type in entities_to_anonymize
        ]
        anonymized_pii_set.update(r.entity_type for r in results_to_anonymize)

        items_to_anonymize = [r.to_dict() for r in results_to_anonymize]

        operation_map = {}
        anonymized_text = None
        if items_to_anonymize:
            generator = RedactGenerator(redact_type, detected_language, counters)
            redact_map = {}
            anonymizer_config = {}
            for item in items_to_anonymize:
                original_text = text[item.get("start"): item.get("end")]
                item["original_text"] = original_text
                entity_type = item.get("entity_type")
                anonymizer_config.setdefault(
                    entity_type,
                    OperatorConfig(
                        "custom",
                        {
                            "lambda": lambda t, _et=entity_type: (
                                redact_map[t]
                                if t in redact_map
                                else (
                                    ""
                                    if t == "PII"
                                    else operation_map.setdefault(
                                        t,
                                        (
                                            redact_map.setdefault(
                                                t, generator.generate(_et)
                                            ),
                                            _et,
                                        ),
                                    )[0]
                                )
                            )
                        },
                    ),
                )

            anonymized_result = _anonymizer.anonymize(
                text=text,
                analyzer_results=results_to_anonymize,
                operators=anonymizer_config,
            )
            anonymized_text = anonymized_result.text

        out_results = get_analyzer_results(
            text, items_to_anonymize, operation_map, detected_language
        )
        sanitized_messages.append(
            {
                "sanitized_text": anonymized_text or text,
                "detected_language": detected_language,
                "msg_id": msg_id,
                "analyzer_results": out_results,
            }
        )

    return {
        "text": sanitized_messages,
        "identified_pii": get_sorted_anonymize_keys(list(identified_pii_set)),
        "anonymized_pii": get_sorted_anonymize_keys(list(anonymized_pii_set)),
        "detected_languages": sorted(
            {
                m["detected_language"]
                for m in sanitized_messages
                if m["detected_language"]
            }
        ),
        "duration": current_milli_time() - start_time,
    }


def _anonymize_passwords(text, analyzer_results):
    """検出されたパスワードを固定長 ######## で置換（公式 anonymize_passwords 互換）。"""
    masked_text = text
    offset = 0
    for result in analyzer_results:
        start, end = result.start + offset, result.end + offset
        password_length = end - start
        masked_text = masked_text[:start] + PASSWORD_REPLACEMENT + masked_text[end:]
        offset += MASK_LENGTH - password_length
    return masked_text


def do_sanitize_credentials(data, analyzer):
    """公式 do_sanitize_credentials 互換。

    - detect_language 例外は捕捉しない（ルート側で 400）。
    - identified/anonymized は既定で last-message 依存（公式バグ互換）。
      settings.credentials_aggregate_all=True で全 message 集約に改善。
    """
    from .validation import validate_message

    start_time = current_milli_time()
    text = data.get("text") if isinstance(data, dict) else None
    if not (isinstance(text, list) or isinstance(text, str)):
        raise ValueError("No valid `text` found")

    messages = [{"text": text, "msg_id": 1}] if isinstance(text, str) else text

    sanitized_messages = []
    last_analyzer_results = []
    any_detected = False

    for message in messages:
        msg_text, msg_id = validate_message(message)

        if len(msg_text.strip()) == 0:
            sanitized_messages.append(_empty_message(msg_text, msg_id, None))
            last_analyzer_results = []
            continue

        # 例外は捕捉しない（公式互換）。
        detected_language = detect_language(msg_text)
        analyzer_language = resolve_analyzer_language(msg_text, detected_language)

        results = analyzer.analyze(
            text=msg_text,
            entities=[PASSWORD_ENTITY],
            language=analyzer_language,
            custom_patterns=[],
        )
        results = sorted(results, key=lambda x: x.start)
        last_analyzer_results = results
        if results:
            any_detected = True

        masked_text = msg_text
        if results:
            masked_text = _anonymize_passwords(msg_text, results)

        sanitized_messages.append(
            {
                "sanitized_text": masked_text,
                "detected_language": detected_language,
                "msg_id": msg_id,
                "analyzer_results": [
                    {
                        "start": r.start,
                        "end": r.end,
                        "detected_language": detected_language,
                        "original_text": msg_text[r.start: r.end],
                        "redact_text": PASSWORD_REPLACEMENT,
                        "entity_type": r.entity_type,
                    }
                    for r in results
                ],
            }
        )

    if settings.credentials_aggregate_all:
        detected = any_detected
    else:
        # 公式バグ互換: 最後の message の結果だけで判定。
        detected = len(last_analyzer_results) > 0

    return {
        "text": sanitized_messages,
        "identified_pii": ["credentials"] if detected else [],
        "anonymized_pii": ["credentials"] if detected else [],
        "detected_languages": sorted(
            {
                m["detected_language"]
                for m in sanitized_messages
                if m["detected_language"]
            }
        ),
        "duration": current_milli_time() - start_time,
    }
