"""従来 PII Service と tanuki-pii の検出精度を HTTP で並べて比較する。

同一データセットを両サービスへ POST し、Kong の anonymize カテゴリ単位で
precision/recall/F1 を算出して並べる（entity_type 名の差は逆引きで吸収）。

実行例:
    PYTHONPATH=. .venv/bin/python eval/compare_services.py \
        --official http://localhost:8080 --candidate http://localhost:9000

出力: コンソール表 + eval/reports/comparison.md + eval/reports/comparison.json
"""

import argparse
import json
import time
from pathlib import Path

import httpx

from tanuki_pii.mappings import get_sorted_anonymize_keys

DATASET = Path(__file__).parent / "fixtures" / "ja_pii_benchmark.json"
REPORT_DIR = Path(__file__).parent / "reports"


def _categories(entity_type):
    cats = get_sorted_anonymize_keys([entity_type])
    return cats  # 通常は1要素


def _primary_category(entity_type):
    cats = _categories(entity_type)
    return cats[0] if cats else entity_type


def _overlap(a0, a1, b0, b1):
    return max(a0, b0) < min(a1, b1)


def post(base, text):
    payload = {"text": text, "anonymize": ["all"], "options": {"redact_type": "placeholder"}}
    t0 = time.perf_counter()
    r = httpx.post(f"{base}/llm/v1/sanitize", json=payload, timeout=60)
    elapsed = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        # サービスがエラー（例: 公式コンテナの 'en' 未ロード 400）→ 検出0扱い。
        return [], elapsed
    body = r.json()
    preds = []
    for msg in body.get("text", []):
        for ar in msg.get("analyzer_results", []):
            preds.append((ar["entity_type"], ar["start"], ar["end"]))
    return preds, elapsed


def evaluate_service(base, cases, warmup=True):
    """各ケースを POST し、カテゴリ別 TP/FP/FN とレイテンシを集計。"""
    if warmup:
        try:
            post(base, cases[0]["text"])  # BERT 遅延ロード等を除外
        except Exception:
            pass

    # category -> {tp, fp, fn, span_tp}
    #   tp/fp/fn: カテゴリ一致での厳密マッチ
    #   span_tp : カテゴリ不問で span が重複（=値が匿名化され得たか。anonymize:all では
    #             匿名化はカテゴリに依存しないため「PII 保護率」を表す）
    stats = {}
    latencies = []

    def bump(cat, key):
        stats.setdefault(cat, {"tp": 0, "fp": 0, "fn": 0, "span_tp": 0})[key] += 1

    for case in cases:
        preds, elapsed = post(base, case["text"])
        latencies.append(elapsed)

        gt = [
            {"cat": _primary_category(e["type"]), "start": e["start"], "end": e["end"]}
            for e in case["entities"]
        ]
        pred_items = [
            {"cats": set(_categories(et)), "start": s, "end": e, "used": False}
            for (et, s, e) in preds
        ]

        for g in gt:
            # 厳密（カテゴリ一致）マッチ。
            hit = None
            for p in pred_items:
                if p["used"]:
                    continue
                if g["cat"] in p["cats"] and _overlap(g["start"], g["end"], p["start"], p["end"]):
                    hit = p
                    break
            if hit is not None:
                hit["used"] = True
                bump(g["cat"], "tp")
            else:
                bump(g["cat"], "fn")
            # span レベル（カテゴリ不問）: 何かしらの予測が重複すれば保護され得た。
            if any(_overlap(g["start"], g["end"], p["start"], p["end"]) for p in pred_items):
                bump(g["cat"], "span_tp")

        # 未使用 pred は FP（primary カテゴリに帰属）。
        for p in pred_items:
            if not p["used"]:
                cat = sorted(p["cats"])[0] if p["cats"] else "unknown"
                bump(cat, "fp")

    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0.0
    return stats, {"p50": p50, "p95": p95, "max": latencies[-1] if latencies else 0.0}


def prf(s):
    tp, fp, fn = s["tp"], s["fp"], s["fn"]
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def micro(stats):
    tp = sum(s["tp"] for s in stats.values())
    fp = sum(s["fp"] for s in stats.values())
    fn = sum(s["fn"] for s in stats.values())
    return prf({"tp": tp, "fp": fp, "fn": fn}), (tp, fp, fn)


def gt_counts(cases):
    counts = {}
    for c in cases:
        for e in c["entities"]:
            cat = _primary_category(e["type"])
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def _span_recall(stats, cats=None):
    if cats is None:
        cats = stats.keys()
    span = sum(stats.get(c, {}).get("span_tp", 0) for c in cats)
    total = sum(stats.get(c, {}).get("tp", 0) + stats.get(c, {}).get("fn", 0) for c in cats)
    return span / total if total else 0.0


def render(off_stats, cand_stats, off_lat, cand_lat, counts, official_label="従来"):
    cats = sorted(set(counts) | set(off_stats) | set(cand_stats))
    lines = []
    lines.append(f"# 日本語PII検出 精度比較（{official_label} vs tanuki-pii）\n")

    # --- A: PII 保護率（span 検出, カテゴリ不問。anonymize:all では匿名化はカテゴリ非依存） ---
    lines.append("## A. PII 保護率（span 検出 / カテゴリ不問）\n")
    lines.append(f"| category | GT件数 | {official_label} | 新 |")
    lines.append("|---|--:|--:|--:|")
    for cat in cats:
        n = counts.get(cat, 0)
        if n == 0:
            continue
        o = _span_recall(off_stats, [cat])
        c = _span_recall(cand_stats, [cat])
        lines.append(f"| {cat} | {n} | {o:.2f} | {c:.2f} |")
    lines.append(
        f"| **overall** | {sum(counts.values())} | **{_span_recall(off_stats):.2f}** "
        f"| **{_span_recall(cand_stats):.2f}** |"
    )
    lines.append("")

    # --- B: カテゴリ正解での精度（厳密: 正しいカテゴリで検出できたか） ---
    lines.append("## B. カテゴリ正解 精度（厳密: 正カテゴリ一致）\n")
    lines.append(f"| category | GT件数 | {official_label} R | 新 R | {official_label} P | 新 P | {official_label} F1 | 新 F1 |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for cat in cats:
        n = counts.get(cat, 0)
        if n == 0 and cat not in off_stats and cat not in cand_stats:
            continue
        op, orr, of = prf(off_stats.get(cat, {"tp": 0, "fp": 0, "fn": 0}))
        cp, cr, cf = prf(cand_stats.get(cat, {"tp": 0, "fp": 0, "fn": 0}))
        lines.append(
            f"| {cat} | {n} | {orr:.2f} | {cr:.2f} | {op:.2f} | {cp:.2f} | {of:.2f} | {cf:.2f} |"
        )
    (op, orr, of), ot = micro(off_stats)
    (cp, cr, cf), ct = micro(cand_stats)
    lines.append(
        f"| **overall(micro)** | {sum(counts.values())} | **{orr:.2f}** | **{cr:.2f}** "
        f"| {op:.2f} | {cp:.2f} | {of:.2f} | {cf:.2f} |"
    )
    lines.append("")
    lines.append(f"- {official_label} micro TP/FP/FN = {ot}")
    lines.append(f"- 新   micro TP/FP/FN = {ct}")
    lines.append("")
    lines.append("## レイテンシ (ms)\n")
    lines.append("| service | p50 | p95 | max |")
    lines.append("|---|--:|--:|--:|")
    lines.append(f"| {official_label} | {off_lat['p50']:.1f} | {off_lat['p95']:.1f} | {off_lat['max']:.1f} |")
    lines.append(f"| 新   | {cand_lat['p50']:.1f} | {cand_lat['p95']:.1f} | {cand_lat['max']:.1f} |")
    lines.append("")
    lines.append("## 方法論・限界\n")
    lines.append(
        "- A=span 検出（カテゴリ不問）。`anonymize:[\"all\"]` では匿名化はカテゴリ非依存のため、"
        "「PII の値が実際に保護され得たか」を表す実運用に近い指標。"
    )
    lines.append(
        "- B=カテゴリ正解（Kong anonymize カテゴリ一致 + span 重複, greedy 1:1）。"
        "正しいカテゴリで分類できたかを見る厳密指標。"
    )
    lines.append(
        "- データは Faker(ja_JP)+テンプレート合成（seed 固定で再現可能）。"
        "マイナンバー/法人番号は有効なチェックディジット。テンプレート由来でやや容易な傾向あり。"
    )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--official", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--official-label", default="従来")
    args = ap.parse_args()

    cases = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    counts = gt_counts(cases)

    print(f"dataset: {len(cases)} cases, {sum(counts.values())} PII instances")
    print("evaluating official ...")
    off_stats, off_lat = evaluate_service(args.official, cases)
    print("evaluating candidate ...")
    cand_stats, cand_lat = evaluate_service(args.candidate, cases)

    report = render(off_stats, cand_stats, off_lat, cand_lat, counts, args.official_label)
    print("\n" + report)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "comparison.md").write_text(report, encoding="utf-8")
    (REPORT_DIR / "comparison.json").write_text(
        json.dumps(
            {
                "counts": counts,
                "official": {"stats": off_stats, "latency": off_lat},
                "candidate": {"stats": cand_stats, "latency": cand_lat},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved: {REPORT_DIR/'comparison.md'}")


if __name__ == "__main__":
    main()
