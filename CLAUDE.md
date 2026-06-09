# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **Custom PII Service** that runs as a sidecar for Kong Gateway's **AI Sanitizer plugin (ai-pii-sanitizer)**. It is a **drop-in replacement** for Kong's official PII Service (same request/response shapes and error shapes) that adds **strong Japanese PII detection**. CPU-only by design (no GPU).

The official Kong implementation lives at `~/work/ai-pii-service` (Flask + Presidio). It is **read-only reference** — used as the contract spec. We reproduce its behavior; we do not copy its code.

## Commands

Setup (Python 3.12; presidio/spacy/torch are not compatible with 3.13+):
```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install torch
python -m spacy download ja_core_news_sm
python -m spacy download en_core_web_lg
```

Run / test / eval (always set `TOKENIZERS_PARALLELISM=false` to silence HF warnings):
```sh
uvicorn tanuki_pii.main:app --port 8080      # run

pytest -m "not bert"                                 # fast: contract/regex/postprocess, no NLP/BERT
pytest                                               # full incl. real spaCy+BERT (first run downloads the model)
pytest tests/test_contract.py::test_basic_japanese_placeholder   # single test
pytest -m bert                                       # only the integration/BERT tests

PYTHONPATH=. python eval/evaluate.py                 # precision/recall/F1 + p50/p95 latency + peak memory
JP_BERT_MODEL=jurabi/bert-ner-japanese PYTHONPATH=. python eval/evaluate.py
```

Golden comparison against the running reference impl (both services up):
```sh
python scripts/golden_compare.py --reference http://localhost:8080 --candidate http://localhost:9000
```

## Architecture

Request flow: `main.py` (FastAPI) → `validation.py` (strict, contract-faithful) → `pii.py` (core orchestration) → `analyzer.py` (`PiiAnalyzer` wraps Presidio) → recognizers → `postprocess.py` → anonymize.

- **`main.py`** — 4 endpoints (`/llm/v1/sanitize`, `/sanitize_credentials`, `/status`, JSON-RPC `POST /`). The `PiiAnalyzer` is built once in the `lifespan` and stored on `app.state.analyzer`. Sync CPU-bound work runs via `run_in_threadpool`. All errors are coerced to `400 {"error": ...}`.
- **`pii.py`** — `do_sanitize_pii` / `do_sanitize_credentials`, the heart. Reproduces the official algorithm: detect with `ALL_ANONYMIZERS`, then filter to `entities_to_anonymize` for redaction (so `analyzer_results` only contains *anonymized* entities while `identified_pii` reflects *all detected* categories). Uses `presidio_anonymizer` with per-message `redact_map` (placeholder counter persists across messages within a request).
- **`analyzer.py`** — builds the Presidio `AnalyzerEngine`: `SpacyNlpEngine` (`ja_core_news_sm` for tokenization only, `en_core_web_lg` for English NER), **ja spaCy NER is deliberately removed** (BERT handles Japanese), plus JP regex recognizers (ja+en), `PasswordRecognizer`, and the BERT recognizer (ja). `PiiAnalyzer.analyze(text, entities, language, custom_patterns)` injects custom patterns as **per-request ad-hoc recognizers** (never added to the global registry).
- **`recognizers/`** — `japanese.py` (regex `PatternRecognizer`s; My Number / Corporate Number use `checksum.py` via `validate_result`), `bert.py` (`JapaneseBertRecognizer`, lazy-loaded transformers pipeline with chunking + offset alignment + a concurrency semaphore), `custom.py` (`regex`-library timeout for ReDoS safety).
- **`postprocess.py`** — `remove_duplicated_span` / `remove_subspan` reproduce the official overlap resolution, **extended** so JP structured PII survives being contained in a broad NER span, while weak structured matches contained in a stronger non-NER pattern (e.g. postal code inside a phone) are dropped.
- **`mappings.py`** — `ANONYMIZE_MAP` (entity→category, JP_* added to existing categories only), `get_entities_to_anonymize`, `get_sorted_anonymize_keys`. `lang.py` — `detect_language` (response value, official) vs `resolve_analyzer_language` (script-heuristic; Japanese chars → `ja` so BERT runs even when langdetect rounds to `en`).

## Critical invariants (do not break these)

These are deliberate contract decisions. Changing them breaks Kong drop-in compatibility or documented behavior — verify against the plan at `~/.claude/plans/ai-pii-service-ja-*.md` before touching.

- **Categories must stay within Kong's set.** Never add new `anonymize` keys. JP postal/address keep their own `entity_type` but reverse-map to `general`.
- **`identified_pii` / `anonymized_pii` are category keys, not entity types.** `analyzer_results` contains only anonymized entities.
- **`all` excludes credentials; only `all_and_credentials` includes them.** `domain` is rejected (400) by default — it's not in the official map (toggle: `ENABLE_DOMAIN_ALIAS`).
- **`text` is always a list in responses** even for string input; empty message → `detected_language: null`; `detect()` exception → `"unknown"` but **structured regex still runs** (`#3b`).
- **credentials masking is fixed `########` (8 chars)** and `identified/anonymized` is decided by the *last* message (official bug, kept; toggle: `CREDENTIALS_AGGREGATE_ALL`).

## Intentional deviations from the official impl

- `custom_patterns` isolated per-request (official has a global-registry leak bug — not reproduced).
- `msg_id` rejects bool (official `isinstance(int)` accepts `True`/`False`).
- Mixed JP+Latin text: only Latin proper-noun **segments** are passed to English NER (avoids spaCy-en over-extending spans across Japanese text), results offset-mapped back and merged.

## Models & licensing

Default BERT model is `tsmatz/xlm-roberta-ner-japanese` (**MIT**, baked into the Docker image). `jurabi/bert-ner-japanese` is lighter but **CC-BY-SA-3.0** (copyleft) — opt-in only via `JP_BERT_MODEL`. Confirm licensing before changing the Docker default or redistributing images.

## Behavior is controlled by env vars

Detection/anonymization toggles live in `config.py` (`Settings`), read from env. Notably `JP_USE_BERT=false` disables BERT for fast startup/tests, and `BERT_CONCURRENCY` / `BERT_MAX_CHARS` / `WORKERS` guard CPU p95 and memory (BERT loads per worker).
