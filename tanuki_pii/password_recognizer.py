"""パスワード/認証情報の検出（公式 PasswordRecognizer 互換 + 日本語 context 追加）。"""

import logging
import re

from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts

from .mappings import PASSWORD_ENTITY

CREDENTIAL_LENGTH = 5
# 公式 context に日本語の語を追加。
CONTEXT = {
    "pin", "code", "credential", "password", "security", "otp", "token",
    "verification", "auth", "authentication", "passcode", "identifier",
    "access", "key", "login", "secret", "unlock", "challenge",
    # 日本語
    "パスワード", "認証コード", "認証", "ワンタイムパスワード", "apiキー",
    "秘密鍵", "アクセストークン", "暗証番号", "トークン", "合言葉",
}
MAX_TOKEN_COUNT = 40
COMMON_WEAK_WORDS = [
    "1234", "123456", "12345678", "qwerty", "letmein", "helloworld",
    "welcome", "admin", "abcd", "abcde",
]

logger = logging.getLogger("PasswordRecognizer")


class PasswordRecognizer(EntityRecognizer):
    def __init__(self, language):
        super().__init__(supported_entities=[PASSWORD_ENTITY])
        self.common_word_threshold = -7
        self.language = language

    def load(self):
        pass

    def detect_weak_passwords(self, token):
        if token.text.lower() in COMMON_WEAK_WORDS or re.search(r"(.)\1{4,}", token.text):
            return [
                RecognizerResult(
                    entity_type=PASSWORD_ENTITY,
                    start=token.idx,
                    end=token.idx + len(token.text),
                    score=0.9,
                )
            ]
        return []

    def detect_unknown_words(self, token):
        if token.is_oov and len(token.text) >= CREDENTIAL_LENGTH:
            return [
                RecognizerResult(
                    entity_type=PASSWORD_ENTITY,
                    start=token.idx,
                    end=token.idx + len(token.text),
                    score=0.85,
                )
            ]
        return []

    def detect_alphanumeric_tokens(self, token):
        if (
            len(token.text) >= CREDENTIAL_LENGTH
            and any(c.isdigit() for c in token.text)
            and any(c.isalpha() for c in token.text)
        ):
            return [
                RecognizerResult(
                    entity_type=PASSWORD_ENTITY,
                    start=token.idx,
                    end=token.idx + len(token.text),
                    score=0.85,
                )
            ]
        return []

    def detect_long_numbers(self, token):
        if token.text.isdigit() and len(token.text) >= 4:
            return [
                RecognizerResult(
                    entity_type=PASSWORD_ENTITY,
                    start=token.idx,
                    end=token.idx + len(token.text),
                    score=0.9,
                )
            ]
        return []

    def analyze(self, text, entities, nlp_artifacts: NlpArtifacts):
        if PASSWORD_ENTITY not in entities:
            return []
        results = []
        doc = nlp_artifacts.tokens
        for sentence in doc.sents:
            if len(sentence) > MAX_TOKEN_COUNT:
                results.extend(self.__analyze_long_sentence(sentence))
            else:
                results.extend(self.__analyze(sentence))
        return results

    def __analyze_long_sentence(self, sentence):
        part = []
        results = []
        for token in sentence:
            if token.text in [",", ";"] and len(part) > 0:
                results.extend(self.__analyze(part))
                part = []
            else:
                part.append(token)
        if len(part) > 0:
            results.extend(self.__analyze(part))
        return results

    def __contains_context(self, sentence):
        for c in CONTEXT:
            for token in sentence:
                if c in token.text.lower():
                    return True
        return False

    def __analyze(self, sentence):
        results = []
        if not self.__contains_context(sentence):
            return results
        for token in sentence:
            if token.is_stop or token.text in CONTEXT or len(token.text) < 4:
                continue
            for detector in (
                self.detect_alphanumeric_tokens,
                self.detect_unknown_words,
                self.detect_weak_passwords,
            ):
                found = detector(token)
                if found:
                    results.extend(found)
                    break
            else:
                results.extend(self.detect_long_numbers(token))
        return results
