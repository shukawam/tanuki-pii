#!/usr/bin/env bash
# 公式コンテナ(kong/ai-pii-service:v0.2.0-ja) と tanuki-pii を起動して精度比較。
# 前提: 公式コンテナイメージがローカルにあること、新サービスは .venv 済み。
set -euo pipefail

CAND_DIR="$HOME/work/tanuki-pii"
OFFICIAL_IMAGE="kong/ai-pii-service:v0.2.0-ja"
OFFICIAL_PORT=8080
CAND_PORT=9000

docker rm -f kong-pii-ja >/dev/null 2>&1 || true
docker run -d --name kong-pii-ja -p "$OFFICIAL_PORT:8080" "$OFFICIAL_IMAGE" >/dev/null
echo "started official container"

cd "$CAND_DIR"
TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 \
  .venv/bin/python -m uvicorn tanuki_pii.main:app --port "$CAND_PORT" \
  --log-level warning >/tmp/candidate.log 2>&1 &
CAND_PID=$!

cleanup() { kill "$CAND_PID" 2>/dev/null || true; docker rm -f kong-pii-ja >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "waiting for services..."
for url in "http://localhost:$OFFICIAL_PORT/llm/v1/status" "http://localhost:$CAND_PORT/llm/v1/status"; do
  for i in $(seq 1 90); do
    curl -sf "$url" >/dev/null 2>&1 && { echo "ready: $url"; break; }
    sleep 2
  done
done

LABEL="公式v0.2.0-ja"
echo "===== 合成データセット比較 ====="
PYTHONPATH=. .venv/bin/python eval/compare_services.py \
  --official "http://localhost:$OFFICIAL_PORT" --candidate "http://localhost:$CAND_PORT" \
  --official-label "$LABEL"

echo "===== 公開自然文(ner-wikipedia) recall 比較 ====="
PYTHONPATH=. .venv/bin/python eval/eval_ner_wikipedia.py \
  --official "http://localhost:$OFFICIAL_PORT" --candidate "http://localhost:$CAND_PORT" --n 1000
