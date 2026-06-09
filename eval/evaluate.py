"""日本語 PII 検出の精度・レイテンシ・メモリ評価。

使い方:
    python -m spacy validate   # モデル確認
    JP_BERT_MODEL=tsmatz/xlm-roberta-ner-japanese python eval/evaluate.py
    JP_BERT_MODEL=jurabi/bert-ner-japanese python eval/evaluate.py

エンティティ単位で precision/recall/F1（完全一致／部分重複）と
p50/p95 レイテンシ、ピークメモリ（任意）を出力する。
"""

import json
import os
import time
from pathlib import Path

from langdetect import DetectorFactory

DetectorFactory.seed = 0

FIXTURES = Path(__file__).parent / "fixtures" / "ja_pii_cases.json"


def _overlap(a_start, a_end, b_start, b_end):
    return max(a_start, b_start) < min(a_end, b_end)


def evaluate():
    from tanuki_pii.analyzer import PiiAnalyzer
    from tanuki_pii.pii import _analyze_message

    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    analyzer = PiiAnalyzer()
    analyzer.warmup()

    tp_exact = tp_partial = fp = fn = 0
    latencies = []

    for case in cases:
        text = case["text"]
        gold = [(et, span) for et, span in case["entities"]]

        t0 = time.perf_counter()
        _lang, results = _analyze_message(analyzer, text, [])
        latencies.append((time.perf_counter() - t0) * 1000)

        pred = [(r.entity_type, text[r.start: r.end], r.start, r.end) for r in results]

        matched_gold = set()
        matched_pred = set()
        # 完全一致（type + テキスト）。
        for gi, (g_type, g_text) in enumerate(gold):
            for pi, (p_type, p_text, _s, _e) in enumerate(pred):
                if pi in matched_pred:
                    continue
                if g_type == p_type and g_text == p_text:
                    tp_exact += 1
                    matched_gold.add(gi)
                    matched_pred.add(pi)
                    break
        # 部分重複（type 一致 + span 重複）。
        for gi, (g_type, g_text) in enumerate(gold):
            if gi in matched_gold:
                continue
            g_start = text.find(g_text)
            g_end = g_start + len(g_text)
            for pi, (p_type, p_text, p_s, p_e) in enumerate(pred):
                if pi in matched_pred:
                    continue
                if g_type == p_type and _overlap(g_start, g_end, p_s, p_e):
                    tp_partial += 1
                    matched_gold.add(gi)
                    matched_pred.add(pi)
                    break

        fn += len(gold) - len(matched_gold)
        fp += len(pred) - len(matched_pred)

    tp = tp_exact + tp_partial

    def _f1(tp, fp, fn):
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return prec, rec, f1

    prec, rec, f1 = _f1(tp, fp, fn)
    prec_e, rec_e, f1_e = _f1(tp_exact, fp + tp_partial, fn)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]

    print("=" * 50)
    print("model:", os.getenv("JP_BERT_MODEL", "tsmatz/xlm-roberta-ner-japanese"))
    print("cases:", len(cases))
    print("-" * 50)
    print(f"[span重複許容] P={prec:.3f} R={rec:.3f} F1={f1:.3f}  (TP={tp} FP={fp} FN={fn})")
    print(f"[完全一致]    P={prec_e:.3f} R={rec_e:.3f} F1={f1_e:.3f}")
    print("-" * 50)
    print(f"latency  p50={p50:.1f}ms  p95={p95:.1f}ms  max={latencies[-1]:.1f}ms")
    print("=" * 50)

    try:
        import resource

        peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS は bytes, Linux は KB。
        peak_mb = peak_kb / (1024 * 1024) if peak_kb > 10**7 else peak_kb / 1024
        print(f"peak memory ~ {peak_mb:.0f} MB")
    except Exception:
        pass


if __name__ == "__main__":
    evaluate()
