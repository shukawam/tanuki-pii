"""日本語正規表現 Recognizer の単体テスト（Presidio エンジン非使用）。"""

import pytest

from tanuki_pii.recognizers.japanese import build_japanese_recognizers


def _recognizers():
    return {r.name: r for r in build_japanese_recognizers("ja")}


def _analyze(recognizer, text):
    return recognizer.analyze(
        text=text, entities=recognizer.supported_entities, nlp_artifacts=None
    )


def test_my_number_valid_detected():
    rec = _recognizers()["JpMyNumberRecognizer"]
    res = _analyze(rec, "マイナンバーは123456789018です")
    assert any(r.entity_type == "JP_MY_NUMBER" for r in res)
    hit = [r for r in res if r.entity_type == "JP_MY_NUMBER"][0]
    assert "123456789018" == "マイナンバーは123456789018です"[hit.start: hit.end]


def test_my_number_invalid_checksum_dropped():
    rec = _recognizers()["JpMyNumberRecognizer"]
    # チェックディジット不一致は validate_result=False で除去される。
    res = _analyze(rec, "番号は123456789012")
    assert not any(r.entity_type == "JP_MY_NUMBER" for r in res)


def test_mobile_phone_detected():
    rec = _recognizers()["JpPhoneRecognizer"]
    res = _analyze(rec, "携帯は090-1234-5678です")
    spans = ["携帯は090-1234-5678です"[r.start: r.end] for r in res]
    assert "090-1234-5678" in spans


def test_postal_marked_detected():
    rec = _recognizers()["JpPostalCodeRecognizer"]
    res = _analyze(rec, "〒100-0001 東京")
    assert any("100-0001" in "〒100-0001 東京"[r.start: r.end] for r in res)


def test_postal_does_not_match_phone():
    rec = _recognizers()["JpPostalCodeRecognizer"]
    res = _analyze(rec, "090-1234-5678")
    spans = ["090-1234-5678"[r.start: r.end] for r in res]
    assert "090-1234" not in spans


def test_address_detected():
    rec = _recognizers()["JpAddressRecognizer"]
    text = "住所は東京都千代田区1-2-3です"
    res = _analyze(rec, text)
    assert any("千代田区" in text[r.start: r.end] for r in res)


def test_passport_detected():
    rec = _recognizers()["JpPassportRecognizer"]
    text = "旅券番号 TK1234567"
    res = _analyze(rec, text)
    assert any(text[r.start: r.end] == "TK1234567" for r in res)


def test_wareki_detected():
    rec = _recognizers()["JpWarekiDateRecognizer"]
    text = "生年月日は令和3年4月1日です"
    res = _analyze(rec, text)
    assert any("令和3年4月1日" == text[r.start: r.end] for r in res)


def test_wareki_abbr_not_match_arbitrary_dot():
    rec = _recognizers()["JpWarekiDateRecognizer"]
    # `.` を任意文字にしないため、R3X4Y1 のような並びはマッチしない。
    res = _analyze(rec, "コードR3X4Y1")
    assert not any(r.entity_type == "JP_DATE_WAREKI" and "R3X4Y1" in "コードR3X4Y1"[r.start:r.end] for r in res)
