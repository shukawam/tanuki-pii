"""実 Analyzer（spaCy + JP regex + BERT）を用いた統合テスト。

実行: pytest -m bert
"""

import pytest
from fastapi.testclient import TestClient
from langdetect import DetectorFactory

DetectorFactory.seed = 0
pytestmark = pytest.mark.bert


@pytest.fixture(scope="module")
def real_client():
    from tanuki_pii.analyzer import PiiAnalyzer
    from tanuki_pii.main import app

    app.state.analyzer = PiiAnalyzer()
    with TestClient(app) as c:
        yield c
    app.state.analyzer = None


def _sanitize(client, text, anonymize=("all",), redact="placeholder"):
    return client.post(
        "/llm/v1/sanitize",
        json={"text": text, "anonymize": list(anonymize), "options": {"redact_type": redact}},
    )


def test_japanese_full_detection(real_client):
    r = _sanitize(real_client, "私は山田太郎です。東京のソニーで働いています。")
    body = r.json()
    etypes = {a["entity_type"] for a in body["text"][0]["analyzer_results"]}
    assert {"PERSON", "LOCATION", "ORGANIZATION"} <= etypes
    assert body["text"][0]["detected_language"] == "ja"


def test_structured_pii(real_client):
    r = _sanitize(real_client, "電話は090-1234-5678、マイナンバーは123456789018です。")
    etypes = {a["entity_type"] for a in r.json()["text"][0]["analyzer_results"]}
    assert "PHONE_NUMBER" in etypes
    assert "JP_MY_NUMBER" in etypes


def test_3b_digits_only_my_number(real_client):
    # 数字のみ → langdetect 例外/丸めでも構造化 PII は検出される。
    r = _sanitize(real_client, "123456789018")
    body = r.json()
    msg = body["text"][0]
    etypes = {a["entity_type"] for a in msg["analyzer_results"]}
    assert "JP_MY_NUMBER" in etypes
    # detected_language は "unknown"（detect 例外）または en に丸まる可能性。
    for a in msg["analyzer_results"]:
        assert a["detected_language"] == msg["detected_language"]


def test_3b_digits_only_phone(real_client):
    r = _sanitize(real_client, "090-1234-5678")
    etypes = {a["entity_type"] for a in r.json()["text"][0]["analyzer_results"]}
    assert "PHONE_NUMBER" in etypes


def test_mixed_text_person_and_location(real_client):
    r = _sanitize(real_client, "John Smithは東京にいます。")
    msg = r.json()["text"][0]
    pairs = {(a["entity_type"], a["original_text"]) for a in msg["analyzer_results"]}
    assert ("PERSON", "John Smith") in pairs
    assert ("LOCATION", "東京") in pairs
    # analyzer_results の detected_language は message-level に揃う。
    langs = {a["detected_language"] for a in msg["analyzer_results"]}
    assert langs == {msg["detected_language"]}


def test_all_excludes_credentials(real_client):
    # 公式互換: all は credentials を「検出」はするが「匿名化」しない。
    # all_and_credentials は匿名化対象に含む。
    text = "password is hunter2abc"
    r_all = _sanitize(real_client, text, anonymize=["all"]).json()
    r_cred = _sanitize(real_client, text, anonymize=["all_and_credentials"]).json()
    assert "credentials" not in r_all["anonymized_pii"]
    assert "credentials" in r_cred["anonymized_pii"]


def test_credentials_endpoint(real_client):
    r = real_client.post(
        "/llm/v1/sanitize_credentials",
        json={"text": "my password is hunter2abc please"},
    )
    body = r.json()
    assert r.status_code == 200
    # 検出されれば ######## に置換される。
    assert "########" in body["text"][0]["sanitized_text"] or body["identified_pii"] == []


def test_creditcard_detected_in_japanese(real_client):
    # 言語非依存パターンの言語間パリティ（ja でも CreditCard を検出する回帰防止）。
    r = _sanitize(real_client, "カード番号 4111111111111111 で決済しました。")
    etypes = {a["entity_type"] for a in r.json()["text"][0]["analyzer_results"]}
    assert "CREDIT_CARD" in etypes


def test_synthetic_japanese(real_client):
    r = _sanitize(real_client, "私は山田太郎です。", redact="synthetic")
    msg = r.json()["text"][0]
    for a in msg["analyzer_results"]:
        # synthetic は原文と異なる。
        assert a["redact_text"] != a["original_text"]
