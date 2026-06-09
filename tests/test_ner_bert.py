"""BERT NER の offset 境界テスト（実モデルをロードするため bert マーク）。

実行: pytest -m bert
"""

import pytest

from tanuki_pii.recognizers.bert import JapaneseBertRecognizer

pytestmark = pytest.mark.bert


@pytest.fixture(scope="module")
def bert():
    rec = JapaneseBertRecognizer(
        model_name="tsmatz/xlm-roberta-ner-japanese",
        score_threshold=0.5,
        max_chars=400,
        concurrency=1,
        language="ja",
    )
    return rec


def test_offset_alignment(bert):
    text = "私は山田太郎です。東京のソニーで働いています。"
    results = bert.analyze(text, entities=["PERSON", "LOCATION", "ORGANIZATION"], nlp_artifacts=None)
    by_type = {}
    for r in results:
        # offset が元文字列スライスと一致すること。
        assert 0 <= r.start < r.end <= len(text)
        by_type.setdefault(r.entity_type, text[r.start: r.end])
    assert by_type.get("PERSON") == "山田太郎"
    assert by_type.get("LOCATION") == "東京"
    assert by_type.get("ORGANIZATION") == "ソニー"


def test_long_text_chunk_offset(bert):
    # max_chars を小さくして chunk 復元のオフセットを検証。
    bert._max_chars = 20
    prefix = "これはテストの文章です。" * 3
    text = prefix + "山田太郎は東京にいます。"
    results = bert.analyze(text, entities=["PERSON", "LOCATION"], nlp_artifacts=None)
    spans = {text[r.start: r.end] for r in results}
    assert "山田太郎" in spans
    assert "東京" in spans


def test_entities_filter(bert):
    text = "山田太郎は東京にいます。"
    results = bert.analyze(text, entities=["LOCATION"], nlp_artifacts=None)
    assert all(r.entity_type == "LOCATION" for r in results)
