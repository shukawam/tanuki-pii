"""テスト共通フィクスチャ。

重い NLP スタックを使わずコントラクトを検証するため、FakeAnalyzer を注入する。
"""

import re

import pytest
from fastapi.testclient import TestClient
from langdetect import DetectorFactory
from presidio_analyzer import RecognizerResult

# langdetect を決定的にする。
DetectorFactory.seed = 0

from tanuki_pii.mappings import CUSTOM_ENTITY, PASSWORD_ENTITY

# (regex, entity_type, score)。テスト入力に必要な最小ルール。
_RULES = [
    (re.compile(r"山田太郎"), "PERSON", 0.95),
    (re.compile(r"John Smith"), "PERSON", 0.95),
    (re.compile(r"東京"), "LOCATION", 0.9),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "EMAIL_ADDRESS", 0.99),
    (re.compile(r"0[789]0-\d{4}-\d{4}"), "PHONE_NUMBER", 0.85),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "JP_MY_NUMBER", 0.6),
]


class FakeAnalyzer:
    """キーワード/正規表現ベースの簡易解析器（テスト専用）。"""

    def __init__(self, rules=None, password_tokens=None):
        self.rules = rules if rules is not None else _RULES
        # credentials テスト用: これらの語を PASSWORD として検出。
        self.password_tokens = password_tokens or []

    @property
    def supported_languages(self):
        return ["en", "ja"]

    def analyze(self, text, entities, language, custom_patterns=None):
        results = []
        ents = set(entities) if entities is not None else None
        for rx, etype, score in self.rules:
            if ents is not None and etype not in ents:
                continue
            for m in rx.finditer(text):
                results.append(
                    RecognizerResult(entity_type=etype, start=m.start(), end=m.end(), score=score)
                )
        # custom_patterns（per-request）
        if custom_patterns and (ents is None or CUSTOM_ENTITY in ents):
            for p in custom_patterns:
                for m in re.finditer(p["regex"], text):
                    results.append(
                        RecognizerResult(
                            entity_type=CUSTOM_ENTITY,
                            start=m.start(),
                            end=m.end(),
                            score=float(p["score"]),
                        )
                    )
        # PASSWORD（credentials）
        if ents is not None and PASSWORD_ENTITY in ents:
            for tok in self.password_tokens:
                idx = text.find(tok)
                if idx != -1:
                    results.append(
                        RecognizerResult(
                            entity_type=PASSWORD_ENTITY, start=idx, end=idx + len(tok), score=0.9
                        )
                    )
        return results


@pytest.fixture
def fake_analyzer():
    return FakeAnalyzer()


@pytest.fixture
def client(fake_analyzer):
    from tanuki_pii.main import app

    app.state.analyzer = fake_analyzer
    with TestClient(app) as c:
        yield c
    app.state.analyzer = None
