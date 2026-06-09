"""日本語 PII ベンチマークデータセット生成（Faker ja_JP + テンプレート）。

各文をセグメント連結で組み立て、PII の start/end を構築時に正確記録する
（text.find に頼らないので重複トークンでも正しい）。マイナンバー/法人番号は
checksum.py の検証式に合わせて有効なチェックディジットで生成する。

実行: PYTHONPATH=. .venv/bin/python eval/gen_dataset.py
出力: eval/fixtures/ja_pii_benchmark.json
"""

import json
import random
from pathlib import Path

from faker import Faker

from tanuki_pii.recognizers.checksum import (
    validate_corporate_number,
    validate_my_number,
)

OUT = Path(__file__).parent / "fixtures" / "ja_pii_benchmark.json"
SEED = 20260608

fake = Faker("ja_JP")


# ---- 有効なチェックディジット付き番号の生成 ----
def gen_my_number(rng):
    body = [rng.randint(0, 9) for _ in range(11)]  # 上位→下位の11桁
    total = sum(body[11 - n] * (n + 1 if n <= 6 else n - 5) for n in range(1, 12))
    rem = total % 11
    check = 0 if rem <= 1 else 11 - rem
    s = "".join(map(str, body)) + str(check)
    assert validate_my_number(s)
    return s


def gen_corporate_number(rng):
    body = [rng.randint(0, 9) for _ in range(12)]  # 下位12桁（上位→下位）
    total = sum(body[12 - n] * (1 if n % 2 == 1 else 2) for n in range(1, 13))
    check = 9 - (total % 9)
    s = str(check) + "".join(map(str, body))
    assert validate_corporate_number(s)
    return s


def gen_passport(rng):
    letters = "".join(rng.choice("ABCDEFGHJKLMNPRSTVWXYZ") for _ in range(2))
    return letters + "".join(str(rng.randint(0, 9)) for _ in range(7))


_ERAS = ["令和", "平成", "昭和"]


def gen_wareki(rng):
    era = rng.choice(_ERAS)
    year = rng.randint(1, 30)
    y = "元" if year == 1 and rng.random() < 0.3 else str(year)
    return f"{era}{y}年{rng.randint(1, 12)}月{rng.randint(1, 28)}日"


def gen_seireki(rng):
    return f"{rng.randint(1960, 2025)}年{rng.randint(1, 12)}月{rng.randint(1, 28)}日"


def _addr(rng):
    return fake.address().replace("\n", " ").strip()


# 値ジェネレータ（entity_type -> callable(rng) -> str）
VALUE_GEN = {
    "PERSON": lambda rng: fake.name(),
    "LOCATION": lambda rng: rng.choice([fake.city(), fake.prefecture()]),
    "ORGANIZATION": lambda rng: fake.company(),
    "PHONE_NUMBER": lambda rng: fake.phone_number(),
    "EMAIL_ADDRESS": lambda rng: fake.email(),
    "JP_MY_NUMBER": gen_my_number,
    "JP_CORPORATE_NUMBER": gen_corporate_number,
    "JP_POSTAL_CODE": lambda rng: fake.postcode(),
    "JP_ADDRESS": lambda rng: _addr(rng),
    "JP_PASSPORT": gen_passport,
    "JP_DATE_WAREKI": gen_wareki,
    "DATE_TIME": gen_seireki,
    "CREDIT_CARD": lambda rng: fake.credit_card_number(),
    "IP_ADDRESS": lambda rng: fake.ipv4(),
    "URL": lambda rng: fake.url(),
}

# テンプレート: 文字列 or ("PII", entity_type)。複数 PII を自然に混在。
TEMPLATES = [
    ["私の名前は", ("PII", "PERSON"), "です。"],
    [("PII", "PERSON"), "は", ("PII", "ORGANIZATION"), "に勤務しています。"],
    [("PII", "PERSON"), "さんは", ("PII", "LOCATION"), "に住んでいます。"],
    ["担当の", ("PII", "PERSON"), "（", ("PII", "ORGANIZATION"), "）がご対応します。"],
    ["お電話は", ("PII", "PHONE_NUMBER"), "までお願いします。"],
    ["ご連絡先メールは", ("PII", "EMAIL_ADDRESS"), "です。"],
    [("PII", "PERSON"), "（電話：", ("PII", "PHONE_NUMBER"), "、メール：", ("PII", "EMAIL_ADDRESS"), "）"],
    ["私のマイナンバーは", ("PII", "JP_MY_NUMBER"), "です。"],
    ["弊社の法人番号は", ("PII", "JP_CORPORATE_NUMBER"), "になります。"],
    ["〒", ("PII", "JP_POSTAL_CODE"), " ", ("PII", "JP_ADDRESS"), " に在住です。"],
    ["送付先は", ("PII", "JP_ADDRESS"), "です。"],
    ["旅券番号は", ("PII", "JP_PASSPORT"), "です。"],
    ["生年月日は", ("PII", "JP_DATE_WAREKI"), "です。"],
    ["契約日は", ("PII", "DATE_TIME"), "でした。"],
    ["カード番号", ("PII", "CREDIT_CARD"), "で決済しました。"],
    ["アクセス元のIPアドレスは", ("PII", "IP_ADDRESS"), "です。"],
    ["詳しくは", ("PII", "URL"), "をご覧ください。"],
    [
        ("PII", "PERSON"), "（", ("PII", "LOCATION"), "在住、電話",
        ("PII", "PHONE_NUMBER"), "）のマイナンバーは", ("PII", "JP_MY_NUMBER"), "です。",
    ],
    [
        ("PII", "ORGANIZATION"), "の", ("PII", "PERSON"),
        "へ", ("PII", "EMAIL_ADDRESS"), "から連絡しました。",
    ],
]

# 各テンプレートを概ね均等に、合計が ~150 になるよう繰り返す。
REPEAT = 8


# ASCII 始まり/数字の PII。日本語かなに直接隣接すると Presidio の \b 境界アンカーが
# 効かず両サービスとも検出できないため、前後にスペースを入れて区切りを作る
# （実テキストでも区切りが入るのが一般的。両サービスに等しく作用するので公平）。
PAD_TYPES = {"EMAIL_ADDRESS", "CREDIT_CARD", "IP_ADDRESS", "URL", "JP_PASSPORT"}


def build(template, rng):
    text = ""
    entities = []
    for part in template:
        if isinstance(part, tuple):  # ("PII", entity_type)
            etype = part[1]
            value = VALUE_GEN[etype](rng)
            pad = etype in PAD_TYPES
            if pad and text and not text.endswith((" ", "（", "：", "/")):
                text += " "
            start = len(text)
            text += value
            entities.append(
                {"type": etype, "text": value, "start": start, "end": len(text)}
            )
            if pad:
                text += " "
        else:
            text += part
    return {"text": text, "entities": entities}


def main():
    random.seed(SEED)
    Faker.seed(SEED)
    rng = random.Random(SEED)

    cases = []
    for _ in range(REPEAT):
        for tmpl in TEMPLATES:
            cases.append(build(tmpl, rng))

    rng.shuffle(cases)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")

    n_pii = sum(len(c["entities"]) for c in cases)
    print(f"wrote {len(cases)} cases, {n_pii} PII instances -> {OUT}")
    # サニティ: span が原文と一致するか。
    bad = 0
    for c in cases:
        for e in c["entities"]:
            if c["text"][e["start"]: e["end"]] != e["text"]:
                bad += 1
    print("span mismatches:", bad)


if __name__ == "__main__":
    main()
