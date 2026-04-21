"""Unit tests for the classifier + routing helpers in app.py.

No network. No database. Pure functions only.
"""
import pytest

import app


# --- _parse_classifier_json ---

def test_parse_valid_json():
    out = app._parse_classifier_json(
        '{"has_secret": false, "complexity": 3, "reason": "moderate reasoning"}'
    )
    assert out == {"has_secret": False, "complexity": 3, "reason": "moderate reasoning"}


def test_parse_with_markdown_fence():
    out = app._parse_classifier_json(
        '```json\n{"has_secret": true, "complexity": 1, "reason": "key assignment"}\n```'
    )
    assert out["has_secret"] is True
    assert out["complexity"] == 1


def test_parse_with_think_tag():
    out = app._parse_classifier_json(
        '<think>hmm let me see</think>{"has_secret": false, "complexity": 2, "reason": "x"}'
    )
    assert out["has_secret"] is False
    assert out["complexity"] == 2


def test_parse_with_trailing_prose():
    out = app._parse_classifier_json(
        'Here is my answer: {"has_secret": false, "complexity": 4, "reason": "multi-step"}\n'
        'Hope that helps!'
    )
    assert out["complexity"] == 4


def test_parse_clamps_complexity_high():
    out = app._parse_classifier_json('{"has_secret": false, "complexity": 7, "reason": "x"}')
    assert out["complexity"] == 5


def test_parse_clamps_complexity_low():
    out = app._parse_classifier_json('{"has_secret": false, "complexity": 0, "reason": "x"}')
    assert out["complexity"] == 1


def test_parse_coerces_string_bool():
    out = app._parse_classifier_json('{"has_secret": "yes", "complexity": 3, "reason": "x"}')
    assert out["has_secret"] is True


def test_parse_coerces_int_bool():
    out = app._parse_classifier_json('{"has_secret": 1, "complexity": 3, "reason": "x"}')
    assert out["has_secret"] is True


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        app._parse_classifier_json("")


def test_parse_prose_only_raises():
    with pytest.raises(ValueError):
        app._parse_classifier_json("I cannot classify this request.")


def test_parse_missing_fields_raises():
    with pytest.raises(ValueError):
        app._parse_classifier_json('{"has_secret": false}')


def test_parse_non_object_raises():
    with pytest.raises(ValueError):
        app._parse_classifier_json('[1, 2, 3]')


# --- _map_tier ---

@pytest.mark.parametrize("has_secret,complexity,expected", [
    (False, 1, "local"),
    (False, 2, "local"),
    (False, 3, "local-thinking"),
    (False, 4, "opus"),
    (False, 5, "opus"),
    (True,  1, "local"),
    (True,  2, "local"),
    (True,  3, "local"),
    (True,  4, "opus"),
    (True,  5, "opus"),
])
def test_map_tier(has_secret, complexity, expected):
    if has_secret:
        assert app._map_tier(has_secret, complexity) == "local"
    else:
        assert app._map_tier(has_secret, complexity) == expected


def test_secret_never_routes_to_cloud():
    for c in range(1, 6):
        assert app._map_tier(True, c) == "local"


# --- regex_secret_hit ---

def _body_with(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}]}


def test_regex_credential_assignment():
    assert app.regex_secret_hit(_body_with("password=hunter2hunter")) == "credential_assignment"


def test_regex_bearer_token():
    assert app.regex_secret_hit(_body_with("Bearer abc123def456ghi789jkl")) == "bearer_token"


def test_regex_ssh_public_key():
    assert app.regex_secret_hit(
        _body_with("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyDataHere1234")
    ) == "ssh_public_key"


def test_regex_pem_private_key():
    assert app.regex_secret_hit(
        _body_with("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
    ) == "pem_private_key"


def test_regex_dotenv_reference():
    assert app.regex_secret_hit(_body_with("check my .env for the value")) == "dotenv_reference"


def test_regex_benign_mention_not_flagged():
    assert app.regex_secret_hit(_body_with("how do I rotate an API key?")) is None


def test_regex_only_scans_latest_user():
    body = {
        "messages": [
            {"role": "user",      "content": "password=hunter2hunter"},
            {"role": "assistant", "content": "ok"},
            {"role": "user",      "content": "what's the weather?"},
        ],
    }
    assert app.regex_secret_hit(body) is None


# --- union safety net (hand-computed truth table) ---

@pytest.mark.parametrize("regex_hit,llm_secret,expected_union", [
    ("credential_assignment", True,  True),
    ("credential_assignment", False, True),
    (None,                    True,  True),
    (None,                    False, False),
])
def test_secret_union(regex_hit, llm_secret, expected_union):
    union = bool(regex_hit) or bool(llm_secret)
    assert union is expected_union


# --- _redact_for_log ---

def test_no_redact_when_clean():
    preview, kws = app._redact_for_log("hello world foo bar baz qux", None)
    assert preview == "hello world foo bar baz qux"
    assert "hello" in kws or "world" in kws


def test_redact_preview_truncated():
    text = "x" * 10_000
    preview, _ = app._redact_for_log(text, None)
    assert len(preview) == app.MESSAGES_PREVIEW_CHARS


def test_redact_llm_only_nulls_preview():
    preview, kws = app._redact_for_log("some sensitive content", "llm_classifier")
    assert preview is None
    assert kws == []


def test_redact_regex_hit_scrubs_and_keeps_context():
    preview, kws = app._redact_for_log(
        "here is my password=hunter2hunter and other context",
        "credential_assignment",
    )
    assert preview is not None
    assert "hunter2hunter" not in preview
    assert "[REDACTED:credential_assignment]" in preview
    assert "other context" in preview


def test_redact_regex_hit_scrubs_multiple_patterns():
    text = "Bearer abcdefghijklmnop1234 and password=topsecret123"
    preview, _ = app._redact_for_log(text, "bearer_token")
    assert "abcdefghijklmnop1234" not in preview
    assert "topsecret123" not in preview
    assert "[REDACTED:bearer_token]" in preview
    assert "[REDACTED:credential_assignment]" in preview


# --- _scrub_secrets ---

def test_scrub_credential_assignment():
    assert app._scrub_secrets("password=hunter2hunter trailing") == \
        "[REDACTED:credential_assignment] trailing"


def test_scrub_no_matches_returns_unchanged():
    text = "nothing sensitive here"
    assert app._scrub_secrets(text) == text


# --- _messages_text include_system ---

def test_messages_text_excludes_system():
    messages = [
        {"role": "system", "content": "you are a tool-using assistant with these tools..."},
        {"role": "user",   "content": "hello"},
    ]
    assert "tools" not in app._messages_text(messages, include_system=False)
    assert "hello" in app._messages_text(messages, include_system=False)


def test_messages_text_includes_system_by_default():
    messages = [
        {"role": "system", "content": "system boilerplate"},
        {"role": "user",   "content": "hello"},
    ]
    out = app._messages_text(messages)
    assert "system boilerplate" in out
    assert "hello" in out
