"""公開自然文（stockmark ner-wikipedia）での recall 測定。

Wikipedia 由来の日本語 NER データ（文字オフセット付き、CC-BY-SA 3.0）を使い、
人名/組織/地名系エンティティ（Kong の general カテゴリ相当）の **検知割合(recall)** を
従来サービスと新サービスで比較する。

データの 8 タイプのうち PII カテゴリに対応するものだけを対象にする:
  人名→PERSON / 法人名・政治的組織名・その他の組織名→ORGANIZATION /
  地名→LOCATION / 施設名→LOCATION(施設)  …すべて general に集約。
  製品名・イベント名は PII 対象外として除外。

注: このデータは上記タイプのみ注釈しており、日付や番号などは未注釈のため
    **precision は直接測れない**。本スクリプトは recall に限定する。

前処理: eval/fixtures/ner_wikipedia_raw.json（GitHub から取得）→ サンプリングして固定。
実行:
  PYTHONPATH=. .venv/bin/python eval/eval_ner_wikipedia.py \
      --official http://localhost:8080 --candidate http://localhost:9000 --n 1000
"""

import argparse
import json
import random
import time
from pathlib import Path

import httpx

from tanuki_pii.mappings import get_sorted_anonymize_keys

RAW = Path(__file__).parent / "fixtures" / "ner_wikipedia_raw.json"
SUBSET = Path(__file__).parent / "fixtures" / "ner_wikipedia_subset.json"
REPORT = Path(__file__).parent / "reports" / "ner_wikipedia_recall.md"

# データのタイプ → 代表エンティティ（すべて general カテゴリ）。
TYPE_MAP = {
    "人名": "PERSON",
    "法人名": "ORGANIZATION",
    "政治的組織名": "ORGANIZATION",
    "その他の組織名": "ORGANIZATION",
    "地名": "LOCATION",
    "施設名": "LOCATION",
}
# 集計表示用のグルーピング。
TYPE_GROUP = {
    "人名": "人名(PERSON)",
    "法人名": "組織(ORG)",
    "政治的組織名": "組織(ORG)",
    "その他の組織名": "組織(ORG)",
    "地名": "地名(LOC)",
    "施設名": "施設(LOC)",
}


RAW_URL = "https://raw.githubusercontent.com/stockmarkteam/ner-wikipedia-dataset/main/ner.json"


def _ensure_raw():
    if RAW.exists():
        return
    print(f"downloading ner-wikipedia (CC-BY-SA 3.0) from {RAW_URL} ...")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    r = httpx.get(RAW_URL, timeout=120, follow_redirects=True)
    r.raise_for_status()
    RAW.write_bytes(r.content)


def prepare_subset(n, seed):
    _ensure_raw()
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    rng.shuffle(raw)
    out = []
    for rec in raw:
        gts = [
            {"type": e["type"], "start": e["span"][0], "end": e["span"][1]}
            for e in rec["entities"]
            if e["type"] in TYPE_MAP
        ]
        if not gts:
            continue
        out.append({"text": rec["text"], "entities": gts})
        if n and len(out) >= n:
            break
    SUBSET.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def general_spans(base, text):
    """general カテゴリの span を返す。サービスが 4xx/5xx を返したら検出0扱い。

    返り値: (spans, elapsed_ms, ok)  ok=False はサービスがエラー（例: 公式コンテナの
    'en' 未ロード 400）で処理できなかったことを示す。
    """
    payload = {"text": text, "anonymize": ["general"], "options": {"redact_type": "placeholder"}}
    t0 = time.perf_counter()
    r = httpx.post(f"{base}/llm/v1/sanitize", json=payload, timeout=60)
    elapsed = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        return [], elapsed, False
    spans = []
    for msg in r.json().get("text", []):
        for ar in msg.get("analyzer_results", []):
            if "general" in get_sorted_anonymize_keys([ar["entity_type"]]):
                spans.append((ar["start"], ar["end"]))
    return spans, elapsed, True


def _overlap(a0, a1, b0, b1):
    return max(a0, b0) < min(a1, b1)


def measure(base, cases, warmup=True):
    if warmup:
        try:
            general_spans(base, cases[0]["text"])
        except Exception:
            pass
    # per group: [hit, total]
    per_group = {}
    hit_total = total = 0
    latencies = []
    errors = 0
    for case in cases:
        spans, elapsed, ok = general_spans(base, case["text"])
        latencies.append(elapsed)
        if not ok:
            errors += 1
        for g in case["entities"]:
            grp = TYPE_GROUP[g["type"]]
            per_group.setdefault(grp, [0, 0])
            per_group[grp][1] += 1
            total += 1
            if any(_overlap(g["start"], g["end"], s0, s1) for s0, s1 in spans):
                per_group[grp][0] += 1
                hit_total += 1
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0.0
    return {
        "per_group": per_group,
        "overall": (hit_total, total),
        "latency": {"p50": p50, "p95": p95},
        "errors": errors,
        "n": len(cases),
    }


def render(off, cand, n_sentences, official_label="従来"):
    groups = sorted({*(off["per_group"] if off else {}), *cand["per_group"]})
    lines = ["# 公開自然文 recall（stockmark ner-wikipedia）\n"]
    lines.append(f"- 対象文数: {n_sentences}（general 相当のエンティティを含む文を抽出）")
    lines.append("- 評価: 各正解エンティティに general カテゴリ予測 span が重複すれば検出（recall）。")
    lines.append("- precision はデータ未注釈タイプがあるため測定対象外。\n")
    header = "| タイプ | 件数 | " + (f"{official_label} recall | " if off else "") + "新 recall |"
    sep = "|---|--:|" + ("--:|" if off else "") + "--:|"
    lines.append(header)
    lines.append(sep)
    for g in groups:
        ch, ct = cand["per_group"].get(g, [0, 0])
        row = f"| {g} | {ct} | "
        if off:
            oh, ot = off["per_group"].get(g, [0, 0])
            row += f"{(oh/ot if ot else 0):.2f} | "
        row += f"{(ch/ct if ct else 0):.2f} |"
        lines.append(row)
    ch, ct = cand["overall"]
    row = f"| **overall** | {ct} | "
    if off:
        oh, ot = off["overall"]
        row += f"**{(oh/ot if ot else 0):.2f}** | "
    row += f"**{(ch/ct if ct else 0):.2f}** |"
    lines.append(row)
    lines.append("\n## エラー率（処理できなかった文）\n")
    lines.append("| service | エラー文数 / 全文 | 率 |")
    lines.append("|---|--:|--:|")
    off_err = 0
    if off:
        off_err, on = off.get("errors", 0), off.get("n", n_sentences)
        lines.append(f"| {official_label} | {off_err} / {on} | {(off_err/on if on else 0):.1%} |")
    ce, cn = cand.get("errors", 0), cand.get("n", n_sentences)
    lines.append(f"| 新   | {ce} / {cn} | {(ce/cn if cn else 0):.1%} |")
    if off and off_err:
        lines.append("\n（単一言語構成のサービスは、langdetect が対応外言語と判定した文で "
                     "対応する NLP エンジン未ロードの 400 となり処理失敗＝検出0として集計）")
    lines.append("\n## レイテンシ (ms)\n")
    lines.append("| service | p50 | p95 |")
    lines.append("|---|--:|--:|")
    if off:
        lines.append(f"| {official_label} | {off['latency']['p50']:.1f} | {off['latency']['p95']:.1f} |")
    lines.append(f"| 新   | {cand['latency']['p50']:.1f} | {cand['latency']['p95']:.1f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--official", default=None)
    ap.add_argument("--n", type=int, default=1000, help="抽出文数（0で全件）")
    ap.add_argument("--seed", type=int, default=20260608)
    ap.add_argument("--official-label", default="従来")
    args = ap.parse_args()

    cases = prepare_subset(args.n, args.seed)
    n_ent = sum(len(c["entities"]) for c in cases)
    print(f"subset: {len(cases)} sentences, {n_ent} entities")

    off = None
    if args.official:
        print("measuring official ...")
        off = measure(args.official, cases)
    print("measuring candidate ...")
    cand = measure(args.candidate, cases)

    report = render(off, cand, len(cases), args.official_label)
    print("\n" + report)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"\nsaved: {REPORT}")


if __name__ == "__main__":
    main()
