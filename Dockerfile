# CPU 専用イメージ。GPU 依存は入れない。
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# CPU-only torch を専用 index から取得（GPU ビルドを避ける）。
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# spaCy モデル（トークナイズ + 英語NER）。
RUN python -m spacy download ja_core_news_sm \
    && python -m spacy download en_core_web_lg

# 既定の BERT モデルは MIT ライセンスの tsmatz。
# jurabi(CC-BY-SA-3.0)を焼き込む場合は --build-arg JP_BERT_MODEL=jurabi/bert-ner-japanese。
ARG JP_BERT_MODEL=tsmatz/xlm-roberta-ner-japanese
ENV JP_BERT_MODEL=${JP_BERT_MODEL}

# モデルをイメージへ事前ダウンロード（起動時 DL を回避）。
RUN python -c "import os; from transformers import AutoTokenizer, AutoModelForTokenClassification; m=os.environ['JP_BERT_MODEL']; AutoTokenizer.from_pretrained(m); AutoModelForTokenClassification.from_pretrained(m)"

COPY . .

# CPU 並行制御の既定値。
ENV OMP_NUM_THREADS=2
ENV TOKENIZERS_PARALLELISM=false
ENV BERT_CONCURRENCY=1
# BERT はワーカー毎にメモリを消費するため既定は 1。
ENV WORKERS=1
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker tanuki_pii.main:app -b 0.0.0.0:${PORT} -w ${WORKERS} --timeout 120 --access-logfile -"]
