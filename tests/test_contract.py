"""コントラクト適合テスト（FakeAnalyzer 使用、NLP 非依存）。"""


def _sanitize(client, body):
    return client.post("/llm/v1/sanitize", json=body)


def test_status(client):
    r = client.get("/llm/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["supported_languages"]) == {"ja", "en"}


def test_basic_japanese_placeholder(client):
    r = _sanitize(
        client,
        {
            "text": "私の名前は山田太郎です。電話は090-1234-5678、メールは taro@example.com です。",
            "anonymize": ["general", "phone", "email"],
            "options": {"redact_type": "placeholder"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["text"], list)
    msg = body["text"][0]
    assert msg["msg_id"] == 1
    assert msg["detected_language"] == "ja"
    etypes = {a["entity_type"] for a in msg["analyzer_results"]}
    assert {"PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS"} <= etypes
    for a in msg["analyzer_results"]:
        assert a["redact_text"].startswith("PLACEHOLDER")
    # identified_pii / anonymized_pii はカテゴリキー。
    assert "general" in body["identified_pii"]
    assert "email" in body["identified_pii"]
    assert body["detected_languages"] == ["ja"]
    assert isinstance(body["duration"], int)


def test_string_input_becomes_list(client):
    r = _sanitize(
        client,
        {"text": "山田太郎", "anonymize": ["general"], "options": {"redact_type": "placeholder"}},
    )
    body = r.json()
    assert isinstance(body["text"], list)
    assert body["text"][0]["msg_id"] == 1


def test_analyzer_results_only_anonymized(client):
    # PERSON は検出されるが anonymize 対象外 → identified_pii に general は出るが
    # analyzer_results には PERSON が出ない。
    r = _sanitize(
        client,
        {
            "text": "山田太郎 と taro@example.com",
            "anonymize": ["email"],
            "options": {"redact_type": "placeholder"},
        },
    )
    body = r.json()
    msg = body["text"][0]
    etypes = {a["entity_type"] for a in msg["analyzer_results"]}
    assert etypes == {"EMAIL_ADDRESS"}
    assert "general" in body["identified_pii"]
    assert "general" not in body["anonymized_pii"]
    assert "email" in body["anonymized_pii"]


def test_empty_message(client):
    r = _sanitize(
        client,
        {
            "text": [{"text": "   ", "msg_id": 7}],
            "anonymize": ["all"],
            "options": {"redact_type": "placeholder"},
        },
    )
    body = r.json()
    msg = body["text"][0]
    assert msg["detected_language"] is None
    assert msg["analyzer_results"] == []
    assert msg["msg_id"] == 7


def test_invalid_redact_type_400(client):
    r = _sanitize(
        client,
        {"text": "山田太郎", "anonymize": ["general"], "options": {"redact_type": "bogus"}},
    )
    assert r.status_code == 400
    assert "error" in r.json()


def test_domain_category_rejected_400(client):
    r = _sanitize(
        client,
        {"text": "x", "anonymize": ["domain"], "options": {"redact_type": "placeholder"}},
    )
    assert r.status_code == 400


def test_msg_id_bool_rejected(client):
    r = _sanitize(
        client,
        {
            "text": [{"text": "山田太郎", "msg_id": True}],
            "anonymize": ["general"],
            "options": {"redact_type": "placeholder"},
        },
    )
    assert r.status_code == 400


def test_custom_pattern_per_request(client):
    r = _sanitize(
        client,
        {
            "text": "secret token ABC-123-XYZ end",
            "anonymize": ["custom"],
            "options": {"redact_type": "placeholder"},
            "custom_patterns": [{"name": "code", "regex": "ABC-\\d{3}-XYZ", "score": 0.9}],
        },
    )
    body = r.json()
    msg = body["text"][0]
    etypes = {a["entity_type"] for a in msg["analyzer_results"]}
    assert "CUSTOM" in etypes
    assert "custom" in body["identified_pii"]


def test_all_excludes_credentials_in_categories(client):
    # all は credentials を除外。FakeAnalyzer は PASSWORD を出さないので
    # ここではバリデーションが通り 200 になることを確認（包含関係は別途）。
    r = _sanitize(
        client,
        {"text": "山田太郎", "anonymize": ["all"], "options": {"redact_type": "placeholder"}},
    )
    assert r.status_code == 200


def test_placeholder_counter_continues_across_messages(client):
    # 公式互換: カウンタはリクエスト内継続。2 message の同一 PII でも別番号。
    r = _sanitize(
        client,
        {
            "text": [
                {"text": "私は山田太郎です。", "msg_id": 1},
                {"text": "また山田太郎です。", "msg_id": 2},
            ],
            "anonymize": ["general"],
            "options": {"redact_type": "placeholder"},
        },
    )
    body = r.json()
    reds = [a["redact_text"] for m in body["text"] for a in m["analyzer_results"]]
    assert reds == ["PLACEHOLDER1", "PLACEHOLDER2"]


def test_domain_alias_disabled_by_default(client):
    r = _sanitize(
        client,
        {"text": "x", "anonymize": ["domain"], "options": {"redact_type": "placeholder"}},
    )
    assert r.status_code == 400


def test_domain_alias_enabled(client, monkeypatch):
    import tanuki_pii.config as cfg

    monkeypatch.setattr(cfg.settings, "enable_domain_alias", True)
    r = _sanitize(
        client,
        {"text": "x", "anonymize": ["domain"], "options": {"redact_type": "placeholder"}},
    )
    assert r.status_code == 200


def test_jsonrpc_sanitize_prompt(client):
    r = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 42,
            "method": "llm.v1.sanitizePrompt",
            "params": {
                "text": "山田太郎",
                "anonymize": ["general"],
                "options": {"redact_type": "placeholder"},
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 42
    assert "result" in body


def test_jsonrpc_invalid_method(client):
    r = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "llm.v1.bogus", "params": {"x": 1}},
    )
    assert r.status_code == 400
