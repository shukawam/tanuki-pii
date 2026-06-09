from tanuki_pii.postprocess import (
    find_all_indexes,
    get_analyzer_results,
    remove_duplicated_span,
    remove_subspan,
)


class R:
    def __init__(self, start, end, entity_type, score=0.5):
        self.start = start
        self.end = end
        self.entity_type = entity_type
        self.score = score


def test_remove_duplicated_span_keeps_highest_score():
    a = R(0, 4, "PERSON", 0.5)
    b = R(0, 4, "ORGANIZATION", 0.9)
    out = remove_duplicated_span([a, b])
    assert len(out) == 1
    assert out[0].entity_type == "ORGANIZATION"


def test_remove_subspan_drops_contained_ner():
    big = R(0, 10, "LOCATION", 0.8)
    small = R(2, 5, "LOCATION", 0.7)
    out = remove_subspan([big, small])
    assert big in out
    assert small not in out


def test_structured_pii_survives_inside_ner():
    # 広い LOCATION が構造化 PII(JP_ADDRESS) を内包しても構造化を残す。
    ner = R(0, 12, "LOCATION", 0.9)
    structured = R(3, 9, "JP_ADDRESS", 0.6)
    out = remove_subspan([ner, structured])
    assert structured in out


def test_find_all_indexes():
    assert find_all_indexes("aXaXa", "aX") == [0, 2]
    assert find_all_indexes("abc", "") == []


def test_get_analyzer_results_basic():
    text = "I am John"
    items = [{"start": 5, "end": 9, "original_text": "John", "entity_type": "PERSON"}]
    op_map = {"John": ("PLACEHOLDER1", "PERSON")}
    out = get_analyzer_results(text, items, op_map, "en")
    assert out == [
        {
            "start": 5,
            "end": 9,
            "detected_language": "en",
            "original_text": "John",
            "redact_text": "PLACEHOLDER1",
            "entity_type": "PERSON",
        }
    ]


def test_get_analyzer_results_merged_entity_expansion():
    # op_map に残ったマージエンティティを全位置展開。
    text = "Shanghai China and Shanghai China"
    items = []
    op_map = {"Shanghai China": ("PLACEHOLDER1", "LOCATION")}
    out = get_analyzer_results(text, items, op_map, "en")
    assert len(out) == 2
    assert [o["start"] for o in out] == [0, 19]
