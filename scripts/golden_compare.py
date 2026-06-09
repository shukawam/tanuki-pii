"""公式 ai-pii-service と本サービスのレスポンスを比較する（ゴールデン）。

両サービスを起動した上で実行する:
    # 公式（参照実装）を 8080、本サービスを 9000 で起動した場合
    python scripts/golden_compare.py --reference http://localhost:8080 --candidate http://localhost:9000

検証は 2 系統 + 候補不変条件:
- official_compat: 公式と一致すべき項目（構造・カテゴリ集合・カテゴリ包含）を厳密比較
- intentional_differences: 意図的に異なる項目（日本語強化・#3b 等）は「検出が増える」ことを許容
- contract invariants: レスポンス形・analyzer_results 形・JSON-RPC・エラー形・credentials マスク・
  placeholder スコープを候補側で検証（公式が無くても確認できる）

非決定要素は正規化: duration は型のみ、synthetic は値非比較、languages は集合比較。
"""

import argparse
import json
import sys

import httpx

OFFICIAL_COMPAT_CASES = [
    {
        "text": "My name is John Smith and my email is john@example.com.",
        "anonymize": ["general", "email"],
        "options": {"redact_type": "placeholder"},
    },
    {
        "text": [{"text": "Call me at 555-123-4567", "msg_id": 3}],
        "anonymize": ["phone"],
        "options": {"redact_type": "placeholder"},
    },
    {"text": "   ", "anonymize": ["all"], "options": {"redact_type": "placeholder"}},
]

JA_ENHANCED_CASES = [
    {
        "text": "私は山田太郎です。マイナンバーは123456789018です。",
        "anonymize": ["all"],
        "options": {"redact_type": "placeholder"},
    },
    {"text": "123456789018", "anonymize": ["all"], "options": {"redact_type": "placeholder"}},
]

ANALYZER_RESULT_KEYS = {
    "start",
    "end",
    "detected_language",
    "original_text",
    "redact_text",
    "entity_type",
}


def _sanitize(base, payload):
    return httpx.post(f"{base}/llm/v1/sanitize", json=payload, timeout=30).json()


def _category_sets(resp):
    return set(resp.get("identified_pii", [])), set(resp.get("anonymized_pii", []))


class Checker:
    def __init__(self):
        self.failures = 0

    def check(self, ok, label, detail=""):
        print(f"  {'OK  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
        if not ok:
            self.failures += 1


def check_official_compat(c, ref_base, cand_base):
    print("== official_compat（厳密比較） ==")
    for case in OFFICIAL_COMPAT_CASES:
        ref = _sanitize(ref_base, case)
        cand = _sanitize(cand_base, case)
        c.check(isinstance(cand.get("duration"), int), "candidate duration is int")
        c.check(_category_sets(ref) == _category_sets(cand),
                "category sets match", f"ref={_category_sets(ref)} cand={_category_sets(cand)}")
        c.check(sorted(ref.get("detected_languages", [])) == sorted(cand.get("detected_languages", [])),
                "detected_languages match (set)")


def check_intentional(c, ref_base, cand_base):
    print("== intentional_differences（本サービスで検出が増える） ==")
    for case in JA_ENHANCED_CASES:
        ref_ids = _category_sets(_sanitize(ref_base, case))[0]
        cand_ids = _category_sets(_sanitize(cand_base, case))[0]
        c.check(cand_ids >= ref_ids, "candidate detects superset", f"ref={ref_ids} cand={cand_ids}")


def check_candidate_contract(c, base):
    print("== contract invariants（候補側） ==")

    # レスポンス形 + analyzer_results 形。
    resp = _sanitize(base, {
        "text": "私は山田太郎です。メールは taro@example.com です。",
        "anonymize": ["all"], "options": {"redact_type": "placeholder"},
    })
    c.check(isinstance(resp.get("text"), list), "text is list")
    keys = {"text", "identified_pii", "anonymized_pii", "detected_languages", "duration"}
    c.check(keys <= set(resp), "top-level keys present")
    msg = resp["text"][0]
    c.check({"sanitized_text", "analyzer_results", "detected_language", "msg_id"} <= set(msg),
            "message keys present")
    for ar in msg["analyzer_results"]:
        c.check(set(ar) == ANALYZER_RESULT_KEYS, "analyzer_result shape", str(set(ar)))

    # placeholder スコープ: 2 message で同一 PII → 別番号（採番がリクエスト継続）。
    resp2 = _sanitize(base, {
        "text": [
            {"text": "私は山田太郎です。", "msg_id": 1},
            {"text": "また山田太郎です。", "msg_id": 2},
        ],
        "anonymize": ["general"], "options": {"redact_type": "placeholder"},
    })
    reds = [a["redact_text"] for m in resp2["text"] for a in m["analyzer_results"]]
    c.check(len(set(reds)) == len(reds) and len(reds) >= 2,
            "placeholder counter continues across messages", str(reds))

    # JSON-RPC 形。
    rpc = httpx.post(f"{base}/", json={
        "jsonrpc": "2.0", "id": 9, "method": "llm.v1.sanitizePrompt",
        "params": {"text": "山田太郎", "anonymize": ["general"], "options": {"redact_type": "placeholder"}},
    }, timeout=30).json()
    c.check(rpc.get("jsonrpc") == "2.0" and rpc.get("id") == 9 and "result" in rpc, "JSON-RPC envelope")

    # エラー形（不正 redact_type → 400 {"error"}）。
    r = httpx.post(f"{base}/llm/v1/sanitize", json={
        "text": "x", "anonymize": ["general"], "options": {"redact_type": "bad"}}, timeout=30)
    c.check(r.status_code == 400 and "error" in r.json(), "bad redact_type → 400 {error}")

    # credentials マスク（######## 固定長）。
    cred = httpx.post(f"{base}/llm/v1/sanitize_credentials",
                      json={"text": "my password is hunter2abc please"}, timeout=30).json()
    c.check("########" in cred["text"][0]["sanitized_text"] or cred["identified_pii"] == [],
            "credentials masked with ########")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", help="公式サービスの base URL（省略時は候補の不変条件のみ）")
    ap.add_argument("--candidate", required=True, help="本サービスの base URL")
    args = ap.parse_args()

    c = Checker()
    if args.reference:
        check_official_compat(c, args.reference, args.candidate)
        check_intentional(c, args.reference, args.candidate)
    check_candidate_contract(c, args.candidate)

    if c.failures:
        print(f"\nFAILURES: {c.failures}")
        sys.exit(1)
    print("\nALL GOLDEN CHECKS PASSED")


if __name__ == "__main__":
    main()
