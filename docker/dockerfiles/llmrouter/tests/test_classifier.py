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

def test_redact_when_secret():
    preview, kws = app._redact_for_log("here is my api key=xyz", True)
    assert preview is None
    assert kws == []


def test_no_redact_when_clean():
    preview, kws = app._redact_for_log("hello world foo bar baz qux", False)
    assert preview == "hello world foo bar baz qux"
    assert "hello" in kws or "world" in kws  # extract_keywords lowercase strips stopwords


def test_redact_preview_truncated():
    text = "x" * 10_000
    preview, _ = app._redact_for_log(text, False)
    assert len(preview) == app.MESSAGES_PREVIEW_CHARS
