"""リクエストの厳格バリデーション（公式 request_validation 互換 + 改善）。

Pydantic の型強制に頼らず、公式の type()/isinstance() ベース挙動を再現する。
改善点（意図的差分）:
- msg_id の bool 拒否（公式は isinstance(int) で True/False が通る）
- custom_patterns の ReDoS 緩和（regex 長・本数の上限）
"""

from .config import settings
from .mappings import REDACT_TYPES, get_entities_to_anonymize


class ValidationError(Exception):
    """400 {"error": ...} に変換されるバリデーション失敗。"""


def _is_real_int(value) -> bool:
    # bool は int のサブクラスなので明示的に除外（意図的改善）。
    return isinstance(value, int) and not isinstance(value, bool)


def validate_custom_patterns(custom_patterns):
    if not isinstance(custom_patterns, list):
        raise ValidationError("Invalid type of `custom_patterns`")
    if len(custom_patterns) > settings.custom_pattern_max_count:
        raise ValidationError("Too many `custom_patterns`")
    for pattern in custom_patterns:
        if not isinstance(pattern, dict):
            raise ValidationError("Invalid item found in `custom_patterns`")
        name = pattern.get("name")
        regex = pattern.get("regex")
        score = pattern.get("score")
        if not (isinstance(name, str) and len(name.strip()) > 0):
            raise ValidationError("Invalid item found in `custom_patterns`")
        if not (isinstance(regex, str) and len(regex.strip()) > 0):
            raise ValidationError("Invalid item found in `custom_patterns`")
        if len(regex) > settings.custom_pattern_max_regex_len:
            raise ValidationError("`custom_patterns` regex too long")
        # score は float のみ（bool/int は不可）。公式と同じく float 厳格。
        if not isinstance(score, float) or isinstance(score, bool) or score < 0 or score > 1:
            raise ValidationError("Invalid item found in `custom_patterns`")


def validate_sanitize_request(data):
    """/llm/v1/sanitize のリクエストを検証し、正規化した dict を返す。"""
    if not isinstance(data, dict):
        raise ValidationError("Invalid request body")

    text = data.get("text")
    if not (isinstance(text, list) or isinstance(text, str)):
        raise ValidationError("No valid `text` found")

    messages = [{"text": text, "msg_id": 1}] if isinstance(text, str) else text

    anonymize = data.get("anonymize")
    try:
        entities_to_anonymize = get_entities_to_anonymize(anonymize)
    except TypeError as e:
        raise ValidationError(str(e))

    custom_patterns = data.get("custom_patterns", [])
    validate_custom_patterns(custom_patterns)

    options = data.get("options")
    if not isinstance(options, dict):
        raise ValidationError("No valid `options` found")

    redact_type = options.get("redact_type")
    if not isinstance(redact_type, str) or redact_type not in REDACT_TYPES:
        raise ValidationError("No valid `redact_type` found")

    return {
        "messages": messages,
        "entities_to_anonymize": entities_to_anonymize,
        "redact_type": redact_type,
        "custom_patterns": custom_patterns,
    }


def validate_message(message):
    """1メッセージを検証し (text, msg_id) を返す。"""
    if not isinstance(message, dict):
        raise ValidationError("Invalid message item")
    msg_id = message.get("msg_id")
    if not _is_real_int(msg_id):
        raise ValidationError("No valid `msg_id` found")
    text = message.get("text")
    if not isinstance(text, str):
        raise ValidationError("`text` in the message is not string")
    if len(text) > settings.max_text_length:
        raise ValidationError("`text` too long")
    return text, msg_id


def validate_rpc_request(data):
    if not data or not isinstance(data, dict):
        return False, "Invalid request: no request body"
    if data.get("jsonrpc") != "2.0":
        return False, "Invalid request: invalid jsonrpc version"
    if not data.get("method"):
        return False, "Invalid request: no method"
    if not data.get("params"):
        return False, "Invalid request: no params"
    if data.get("id") is None:
        return False, "Invalid request: no id"
    return True, None
