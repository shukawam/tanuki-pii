"""日本語 BERT NER Recognizer（transformers, CPU）。

- 既定 tsmatz/xlm-roberta-ner-japanese（MIT, fast tokenizer → offset 利用可）
- jurabi/bert-ner-japanese（CC-BY-SA-3.0, slow tokenizer → offset を自前アライン）
長文は文字数で chunking し、各 chunk のオフセットを元テキスト基準に復元する。
CPU の p95 保護のためセマフォで同時推論数を制限する。
"""

import logging
import threading

from presidio_analyzer import EntityRecognizer, RecognizerResult

logger = logging.getLogger("JapaneseBertRecognizer")

# モデルラベル → Presidio エンティティ。tsmatz と jurabi の両系統を網羅。
LABEL_MAP = {
    # tsmatz (xlm-roberta)
    "PER": "PERSON",
    "ORG": "ORGANIZATION",
    "ORG-P": "ORGANIZATION",
    "ORG-O": "ORGANIZATION",
    "LOC": "LOCATION",
    "INS": "LOCATION",
    # jurabi (日本語ラベル)
    "人名": "PERSON",
    "法人名": "ORGANIZATION",
    "政治的組織名": "ORGANIZATION",
    "その他の組織名": "ORGANIZATION",
    "地名": "LOCATION",
    "施設名": "LOCATION",
    # PRD/EVT/製品名/イベント名 は対象外（マップしない）
}

_BERT_SEMAPHORE = None


def _get_semaphore(concurrency):
    global _BERT_SEMAPHORE
    if _BERT_SEMAPHORE is None:
        _BERT_SEMAPHORE = threading.Semaphore(max(1, concurrency))
    return _BERT_SEMAPHORE


class JapaneseBertRecognizer(EntityRecognizer):
    SUPPORTED = ["PERSON", "LOCATION", "ORGANIZATION"]

    def __init__(self, model_name, score_threshold=0.5, max_chars=400,
                 concurrency=1, language="ja"):
        # EntityRecognizer.__init__ が load() を呼ぶため、属性を先に設定する。
        self._model_name = model_name
        self._threshold = score_threshold
        self._max_chars = max_chars
        self._concurrency = concurrency
        self._pipeline = None
        self._load_lock = threading.Lock()
        super().__init__(
            supported_entities=self.SUPPORTED,
            supported_language=language,
            name="JapaneseBertRecognizer",
        )

    def load(self):
        # Presidio のフック。実モデルは初回 analyze 時に遅延ロードする。
        return

    def _ensure_pipeline(self):
        # ダブルチェックロックで初回の重複ロード/メモリスパイクを防ぐ。
        if self._pipeline is not None:
            return
        with self._load_lock:
            if self._pipeline is not None:
                return
            from transformers import (
                AutoModelForTokenClassification,
                AutoTokenizer,
                pipeline,
            )

            tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            model = AutoModelForTokenClassification.from_pretrained(self._model_name)
            self._pipeline = pipeline(
                "token-classification",
                model=model,
                tokenizer=tokenizer,
                aggregation_strategy="simple",
            )

    def _chunks(self, text):
        """文字数で chunk 分割し (chunk_text, base_offset) を返す。

        句点・読点・改行を優先境界にして単純分割する。
        """
        if len(text) <= self._max_chars:
            yield text, 0
            return
        start = 0
        n = len(text)
        while start < n:
            end = min(start + self._max_chars, n)
            if end < n:
                # 近傍の区切りで切る。
                window = text[start:end]
                cut = max(
                    window.rfind("。"),
                    window.rfind("、"),
                    window.rfind("\n"),
                )
                if cut > 0:
                    end = start + cut + 1
            yield text[start:end], start
            start = end

    def _align(self, original, base, word, approx_start, approx_end, cursor):
        """offset が None の場合に word を元テキストから探してアラインする。

        cursor は chunk ローカルなので、検索は現在 chunk の base+cursor から始める
        （後続 chunk で同じ語が前 chunk の位置にマッチするのを防ぐ）。
        """
        if approx_start is not None and approx_end is not None:
            return base + approx_start, base + approx_end
        if not word:
            return None
        idx = original.find(word, base + cursor)
        if idx == -1:
            idx = original.find(word, base)
        if idx == -1:
            return None
        return idx, idx + len(word)

    def analyze(self, text, entities, nlp_artifacts=None):
        wanted = [e for e in self.SUPPORTED if e in entities]
        if not wanted:
            return []
        self._ensure_pipeline()

        results = []
        sem = _get_semaphore(self._concurrency)
        for chunk_text, base in self._chunks(text):
            with sem:
                preds = self._pipeline(chunk_text)
            cursor = 0
            for p in preds:
                label = p.get("entity_group") or p.get("entity")
                entity_type = LABEL_MAP.get(label)
                if entity_type is None or entity_type not in wanted:
                    continue
                score = float(p.get("score", 0.0))
                if score < self._threshold:
                    continue
                aligned = self._align(
                    text, base, p.get("word", ""),
                    p.get("start"), p.get("end"), cursor,
                )
                if aligned is None:
                    continue
                start, end = aligned
                cursor = max(cursor, end - base)
                if start >= end:
                    continue
                results.append(
                    RecognizerResult(
                        entity_type=entity_type,
                        start=start,
                        end=end,
                        score=score,
                    )
                )
        return results
