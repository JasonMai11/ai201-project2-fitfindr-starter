"""
Tests for agent.parse_query — the LLM-based parser and its regex fallback.

Uses a mocked Groq client (patched on the `agent` module, since parse_query
imports `_get_groq_client` into agent's namespace) so tests are fast,
deterministic, and need no API key or network.
"""

import pytest

import agent


# ── a fake Groq client returning canned JSON ─────────────────────────────────

class _FakeResponse:
    def __init__(self, content):
        message = type("Msg", (), {"content": content})()
        self.choices = [type("Choice", (), {"message": message})()]


class _FakeClient:
    def __init__(self, content):
        completions = type("C", (), {"create": lambda _self, **kw: _FakeResponse(content)})()
        self.chat = type("Chat", (), {"completions": completions})()


@pytest.fixture
def mock_llm(monkeypatch):
    """Return a setter that makes parse_query's LLM return the given JSON string."""
    def _set(json_content):
        monkeypatch.setattr(agent, "_get_groq_client", lambda: _FakeClient(json_content))
    return _set


# ── LLM happy path ───────────────────────────────────────────────────────────

def test_parse_query_llm_extracts_fields(mock_llm):
    mock_llm('{"description": "button shirt", "size": null, "max_price": 40, "category": "tops"}')
    parsed = agent.parse_query("I wear shorts, I want a button shirt under $40")
    assert parsed == {
        "description": "button shirt",
        "size": None,
        "max_price": 40.0,
        "category": "tops",
    }


def test_parse_query_invalid_category_becomes_none(mock_llm):
    # A category outside the dataset's set must be ignored (→ None).
    mock_llm('{"description": "ballgown", "size": null, "max_price": null, "category": "dresses"}')
    parsed = agent.parse_query("a designer ballgown")
    assert parsed["category"] is None


def test_parse_query_llm_coerces_types(mock_llm):
    # size given as string, price as string number → coerced; empty-ish size → None.
    mock_llm('{"description": "track jacket", "size": "M", "max_price": "45"}')
    parsed = agent.parse_query("track jacket size M")
    assert parsed["description"] == "track jacket"
    assert parsed["size"] == "M"
    assert parsed["max_price"] == 45.0


# ── fallback to regex ─────────────────────────────────────────────────────────

def test_parse_query_falls_back_on_error(monkeypatch):
    # LLM call raises → parse_query must fall back to the regex parser, not crash.
    def _boom():
        raise RuntimeError("groq is down")
    monkeypatch.setattr(agent, "_get_groq_client", _boom)

    parsed = agent.parse_query("vintage graphic tee under $30")
    # Regex fallback still extracts price and a description.
    assert parsed["max_price"] == 30.0
    assert "graphic" in parsed["description"].lower()


def test_parse_query_falls_back_on_bad_json(mock_llm):
    mock_llm("not valid json at all")
    parsed = agent.parse_query("flowy midi skirt under $40")
    assert parsed["max_price"] == 40.0
    assert "skirt" in parsed["description"].lower()


def test_regex_fallback_directly():
    # The fallback parser on its own (no LLM involved).
    parsed = agent._parse_query_regex("90s track jacket in size M")
    assert parsed["size"] == "M"
    assert parsed["max_price"] is None
