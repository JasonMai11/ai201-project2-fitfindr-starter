"""
Tests for the three FitFindr tools, with at least one test per documented
failure mode (see the Error Handling table in planning.md):

    search_listings  → no results match            → returns []
    suggest_outfit   → wardrobe is empty            → general advice, no crash
    create_fit_card  → outfit missing/incomplete    → error string, no exception

The two LLM-backed tools (suggest_outfit, create_fit_card) use a mocked Groq
client so the tests are fast, deterministic, and need no API key or network.
"""

import pytest

import tools
from utils.data_loader import get_empty_wardrobe


# ── a fake Groq client (no network) ──────────────────────────────────────────

class _FakeResponse:
    def __init__(self, content):
        message = type("Msg", (), {"content": content})()
        self.choices = [type("Choice", (), {"message": message})()]


class _FakeCompletions:
    def __init__(self, calls, content):
        self._calls = calls
        self._content = content

    def create(self, **kwargs):
        self._calls.append(kwargs)          # record args so tests can inspect prompts
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, calls, content):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(calls, content)})()


@pytest.fixture
def fake_groq(monkeypatch):
    """Patch _get_groq_client so LLM tools return a canned response.

    Yields the list of recorded create() kwargs so tests can assert on the
    prompts that were sent (and on whether the client was called at all).
    """
    calls = []
    monkeypatch.setattr(tools, "_get_groq_client", lambda: _FakeClient(calls, "MOCK OUTPUT"))
    return calls


def _user_prompt(calls):
    """Pull the user-message content from the most recent recorded LLM call."""
    messages = calls[-1]["messages"]
    return next(m["content"] for m in messages if m["role"] == "user")


NEW_ITEM = {
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "category": "tops",
    "colors": ["black"],
    "style_tags": ["graphic tee", "vintage"],
    "size": "L",
    "price": 24.0,
    "platform": "depop",
    "brand": None,
}


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = tools.search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, no exception.
    results = tools.search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = tools.search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    # "M" should match listings like size "M" and "S/M" (case-insensitive substring).
    results = tools.search_listings("jacket", size="M")
    assert all("m" in item["size"].lower() for item in results)


def test_search_category_filter():
    results = tools.search_listings("shirt", category="tops")
    assert results  # there are matching tops
    assert all(item["category"] == "tops" for item in results)


def test_search_category_excludes_wrong_type():
    # Regression: "white shirt" must not return shoes (the Off-White sneakers bug).
    results = tools.search_listings("white shirt", category="tops")
    assert all(item["category"] == "tops" for item in results)
    assert not any(item["category"] == "shoes" for item in results)


# ── refine_search (stretch) ───────────────────────────────────────────────────

def test_refine_search_relaxes_size():
    # A bogus size yields nothing directly; refine_search drops it and finds tops.
    parsed = {"description": "graphic tee", "size": "ZZZ",
              "max_price": None, "category": "tops"}
    assert tools.search_listings(parsed["description"], parsed["size"],
                                 parsed["max_price"], parsed["category"]) == []
    refined = tools.refine_search(parsed)
    assert refined
    assert all(item["category"] == "tops" for item in refined)


def test_refine_search_exhausted_returns_empty():
    # Nothing matches the description at all → relaxing constraints can't help.
    parsed = {"description": "designer ballgown", "size": "XXS",
              "max_price": 5.0, "category": None}
    assert tools.refine_search(parsed) == []


# ── suggest_outfit ──────────────────────────────────────────────────────────

def test_suggest_outfit_empty_wardrobe(fake_groq):
    # Failure mode: empty wardrobe → returns a non-empty string, no crash.
    result = tools.suggest_outfit(NEW_ITEM, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip()
    # It should take the general-advice branch, not pretend to list owned pieces.
    prompt = _user_prompt(fake_groq)
    assert "haven't told us" in prompt.lower() or "what's in their closet" in prompt.lower()


def test_suggest_outfit_with_wardrobe(fake_groq):
    wardrobe = {"items": [
        {"name": "Baggy straight-leg jeans", "category": "bottoms",
         "colors": ["blue"], "style_tags": ["denim", "baggy"]},
    ]}
    result = tools.suggest_outfit(NEW_ITEM, wardrobe)
    assert result.strip()
    # The owned piece should appear in the prompt sent to the LLM.
    assert "Baggy straight-leg jeans" in _user_prompt(fake_groq)


# ── create_fit_card ───────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit(fake_groq):
    # Failure mode: empty/whitespace outfit → error string, no exception,
    # and the LLM is never called.
    assert tools.create_fit_card("", NEW_ITEM).strip()
    assert tools.create_fit_card("   ", NEW_ITEM).strip()
    assert fake_groq == []  # guarded before any API call


def test_create_fit_card_mentions_item_details(fake_groq):
    tools.create_fit_card("Pair it with baggy jeans and combat boots.", NEW_ITEM)
    prompt = _user_prompt(fake_groq)
    assert "$24" in prompt
    assert "depop" in prompt
