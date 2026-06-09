FROM kong/ai-pii-service:v0.2.0-ja
RUN python -m spacy download en_core_web_lg
RUN printf 'nlp_engine_name: spacy\nmodels:\n  - lang_code: ja\n    model_name: ja_core_news_lg\n  - lang_code: en\n    model_name: en_core_web_lg\n' \
    > /app/ai_pii_service/nlp_engine_conf.yml
