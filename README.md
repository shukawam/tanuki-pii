# tanuki-pii

> [!NOTE]
> **パッケージ名の由来**
> たぬきには日本語で「化かす」という意味合いがあります。このリポジトリは、日本語の PII をマスキング（＝化かす）することから `tanuki-pii` と名付けられました。

Kong Gateway の AI Sanitizer プラグイン（ai-pii-sanitizer） の sidecar として動作する、日本語 PII 検出を強化した Custom PII Service です。現在はCPUでのみ動作します。

Kong 公式 PII Service と同じ I/F を保つドロップイン互換を維持しつつ、日本語の人名/組織/地名は BERT 日本語 NER、マイナンバー・電話・住所などの構造化 PII は正規表現 Recognizerで検出精度を底上げをしています。

## アーキテクチャ

- API: FastAPI（`/llm/v1/sanitize`, `/llm/v1/sanitize_credentials`, `/llm/v1/status`, JSON-RPC `POST /`）
- 検出コア: Microsoft Presidio
  - NLP エンジン: spaCy（`ja_core_news_sm` はトークナイズ専用、`en_core_web_lg` は英語 NER）
  - 日本語 NER: BERT（既定 `tsmatz/xlm-roberta-ner-japanese` / MIT）
  - 日本語構造化 PII: 正規表現 Recognizer（ja/en 両登録）
  - 認証情報: `PasswordRecognizer`（日本語 context 追加）
- 匿名化: placeholder（`PLACEHOLDER{n}`）/ synthetic（Faker, `ja_JP`/`en_US`）

詳細な設計と公式実装との差分は `…/.claude/plans/ai-pii-service-ja-*.md` を参照。

## BERT モデルとライセンス

| モデル                                    | ライセンス   | 備考                                                    |
| ----------------------------------------- | ------------ | ------------------------------------------------------- |
| `tsmatz/xlm-roberta-ner-japanese`（既定） | MIT          | ~0.3B。配布 Docker 既定。p95/メモリはリリース条件で確認 |
| `jurabi/bert-ner-japanese`                | CC-BY-SA-3.0 | 軽量だがコピーレフト。`JP_BERT_MODEL` でオプトイン      |

## ローカル起動

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install torch
python -m spacy download ja_core_news_sm
python -m spacy download en_core_web_lg
uvicorn tanuki_pii.main:app --port 8080
```

## API 例

```sh
curl -s localhost:8080/llm/v1/status

curl -s -X POST localhost:8080/llm/v1/sanitize -H 'Content-Type: application/json' \
  -d '{"text":"私は山田太郎です。電話は090-1234-5678、マイナンバーは123456789018です。",
       "anonymize":["all"],"options":{"redact_type":"placeholder"}}'
```

## テスト

```sh
pytest                 # 全テスト（BERT 含む。初回はモデル DL）
pytest -m "not bert"   # 高速（NLP/BERT 非依存のコントラクト・正規表現・後処理）
```

## 精度・レイテンシ評価

```sh
PYTHONPATH=. python eval/evaluate.py
JP_BERT_MODEL=jurabi/bert-ner-japanese PYTHONPATH=. python eval/evaluate.py
```

## ゴールデン比較（公式実装との差分検証）

公式 `ai-pii-service` と本サービスを両方起動して比較:

```sh
python scripts/golden_compare.py --reference http://localhost:8080 --candidate http://localhost:9000
```

## Docker（CPU）

```sh
docker build -t tanuki-pii .
docker run -p 9000:8080 tanuki-pii
# jurabi を焼き込む場合:
docker build --build-arg JP_BERT_MODEL=jurabi/bert-ner-japanese -t tanuki-pii:jurabi .
```

## Kong 結合確認

```sh
docker compose -f docker-compose.kong.yml up --build
```

## 主な環境変数

| 変数                        | 既定                              | 説明                                                             |
| --------------------------- | --------------------------------- | ---------------------------------------------------------------- |
| `JP_BERT_MODEL`             | `tsmatz/xlm-roberta-ner-japanese` | BERT モデル                                                      |
| `JP_USE_BERT`               | `true`                            | BERT 無効化（軽量起動/テスト用）                                 |
| `JP_NER_SCORE_THRESHOLD`    | `0.5`                             | BERT スコア閾値                                                  |
| `BERT_CONCURRENCY`          | `1`                               | 同時 BERT 推論数（p95 保護）                                     |
| `BERT_MAX_CHARS`            | `400`                             | chunking 文字数（512 token 対策）                                |
| `WORKERS`                   | `1`                               | Gunicorn ワーカー数（BERT はワーカー毎にメモリ消費）             |
| `ENABLE_DOMAIN_ALIAS`       | `false`                           | `domain` を url 別名として受理（既定は公式互換で 400）           |
| `CREDENTIALS_AGGREGATE_ALL` | `false`                           | credentials の集約を全 message に（既定は公式互換=last-message） |

## 公式実装との差分（要点）

- `custom_patterns` は per-request 隔離（公式の global registry バグを意図的に非再現）
- `detect()` 例外時も構造化 regex は実行（数字のみ PII を検出。`detected_language` は "unknown"）
- 混在文はラテン固有名詞セグメントのみ英語 NER にかけマージ
- `msg_id` の bool 拒否（公式は `isinstance(int)` で通る）
- `domain` は既定で 400（公式 ANONYMIZE_MAP に無いため）
