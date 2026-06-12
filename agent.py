"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import re

from tools import (
    search_listings,
    refine_search,
    suggest_outfit,
    create_fit_card,
    _get_groq_client,
    _MODEL,
)

# Categories the LLM may tag a query with (must match the dataset's categories).
_CATEGORIES = {"tops", "bottoms", "outerwear", "shoes", "accessories"}


# ── query parsing ─────────────────────────────────────────────────────────────

def parse_query(query: str) -> dict:
    """
    Extract structured search parameters from a natural-language query.

    Returns a dict: {"description": str, "size": str | None,
                     "max_price": float | None, "category": str | None}.

    Primary path uses the Groq LLM (JSON mode), which understands intent and can
    tell the item the user *wants* from items they merely mention owning/wearing
    (e.g. "I wear shorts, I want a button shirt" → description "button shirt"),
    and tags the request with a category so a "shirt" request can't return shoes.
    If the call fails or returns malformed JSON, we fall back to the deterministic
    regex parser so the agent never crashes.
    """
    system_prompt = (
        "You extract structured search filters from a shopper's request for a "
        "secondhand clothing item. Respond with a JSON object with exactly these "
        "keys:\n"
        '  "description": a short phrase for the ITEM THE USER WANTS TO BUY '
        "(e.g. \"button shirt\", \"vintage graphic tee\"). Exclude anything they "
        "say they already own or wear, and exclude size/price.\n"
        '  "size": the requested size as a string, or null if none given.\n'
        '  "max_price": the maximum price as a number, or null if none given.\n'
        '  "category": the item type, one of "tops", "bottoms", "outerwear", '
        '"shoes", "accessories", or null if unclear.\n'
        "Return only the JSON object."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)

        description = str(data.get("description") or "").strip()
        if not description:
            raise ValueError("LLM returned an empty description")

        size = data.get("size")
        size = str(size).strip() if size not in (None, "") else None

        max_price = data.get("max_price")
        max_price = float(max_price) if max_price not in (None, "") else None

        # Only accept a category the dataset actually uses; otherwise ignore it.
        category = data.get("category")
        category = category.lower() if isinstance(category, str) else None
        if category not in _CATEGORIES:
            category = None

        return {
            "description": description,
            "size": size,
            "max_price": max_price,
            "category": category,
        }
    except Exception:
        # Network error, bad JSON, missing/invalid fields → deterministic fallback.
        return _parse_query_regex(query)


# Regex fallback — deterministic, no API call. Used if the LLM parse fails.

# Price: prefer a keyworded amount ("under $30", "less than 25"), else any "$30".
_KEYWORD_PRICE_RE = re.compile(
    r"(?:under|below|less than|max(?:imum)?|<=?)\s*\$?\s*(\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
_BARE_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
# Size: "size M", "in size M", "size 8" → captures the token after "size".
_SIZE_RE = re.compile(r"\bsize\s+([A-Za-z0-9/]+)", re.IGNORECASE)


def _parse_query_regex(query: str) -> dict:
    """Regex/string fallback parser (no LLM call). Same return shape as parse_query."""
    spans_to_remove = []

    # max_price
    max_price = None
    price_match = _KEYWORD_PRICE_RE.search(query) or _BARE_PRICE_RE.search(query)
    if price_match:
        max_price = float(price_match.group(1))
        spans_to_remove.append(price_match.span())

    # size
    size = None
    size_match = _SIZE_RE.search(query)
    if size_match:
        size = size_match.group(1)
        spans_to_remove.append(size_match.span())

    # description = query minus the matched price/size spans, whitespace collapsed
    description = query
    for start, end in sorted(spans_to_remove, reverse=True):
        description = description[:start] + description[end:]
    description = re.sub(r"\s+", " ", description).strip()

    # Regex can't reliably infer a category — leave it None (shape stays consistent).
    return {
        "description": description,
        "size": size,
        "max_price": max_price,
        "category": None,
    }


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into description / size / max_price.
    parsed = parse_query(query)
    session["parsed"] = parsed

    # Step 3: search the listings.
    results = search_listings(
        parsed["description"], parsed["size"], parsed["max_price"], parsed["category"]
    )
    session["search_results"] = results

    # No results → retry with relaxed constraints (stretch tool) before giving up.
    if not results:
        results = refine_search(parsed)
        session["search_results"] = results

    # Still nothing → stop with a helpful message, before any LLM calls.
    if not results:
        session["error"] = (
            f"No listings matched '{parsed['description']}'. "
            "Try fewer keywords, a higher price, or removing the size filter."
        )
        return session

    # Step 4: select the most relevant result.
    session["selected_item"] = results[0]

    # Step 5: suggest an outfit using the user's wardrobe.
    session["outfit_suggestion"] = suggest_outfit(session["selected_item"], wardrobe)

    # Step 6: turn the outfit into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
