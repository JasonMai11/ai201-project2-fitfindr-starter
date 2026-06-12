"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── helpers ─────────────────────────────────────────────────────────────────────

# Common filler words that carry no search signal — dropped before scoring.
_STOPWORDS = {
    "a", "an", "the", "for", "with", "in", "of", "and", "to", "my", "me",
    "looking", "want", "need",
}


def _tokenize(text: str) -> set[str]:
    """Split text into a set of lowercase word tokens (>=2 chars, no stopwords)."""
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 2 and w not in _STOPWORDS}


# ── Groq client ───────────────────────────────────────────────────────────────

_MODEL = "llama-3.3-70b-versatile"


def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _describe_item(item: dict) -> str:
    """One-line description of a listing or wardrobe item for use in a prompt."""
    name = item.get("title") or item.get("name") or "item"
    parts = [name]
    if item.get("category"):
        parts.append(f"({item['category']})")
    if item.get("colors"):
        parts.append("colors: " + ", ".join(item["colors"]))
    if item.get("style_tags"):
        parts.append("style: " + ", ".join(item["style_tags"]))
    return " — ".join(parts)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
    category: str | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, optional price ceiling, and optional category.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.
        category:    One of tops/bottoms/outerwear/shoes/accessories to restrict
                     results to that category, or None to skip category filtering.
                     Prevents e.g. a "white shirt" request from returning shoes
                     just because "white" appears in a shoe's title.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    query_tokens = _tokenize(description)

    # No keywords to match on → nothing scores above 0 (strict).
    if not query_tokens:
        return []

    # Field weights — title/tags/category matches signal more relevance.
    field_weights = (
        ("title", 3),
        ("style_tags", 2),
        ("category", 2),
        ("description", 1),
        ("brand", 1),
        ("colors", 1),
    )

    scored = []
    for listing in listings:
        # Filter: price ceiling (inclusive), case-insensitive size substring, category.
        if max_price is not None and listing["price"] > max_price:
            continue
        if size is not None and size.lower() not in listing["size"].lower():
            continue
        if category is not None and listing["category"].lower() != category.lower():
            continue

        # Score: weighted keyword overlap across fields.
        score = 0
        for field, weight in field_weights:
            value = listing.get(field)
            if value is None:
                continue
            field_text = " ".join(value) if isinstance(value, list) else str(value)
            field_tokens = _tokenize(field_text)
            score += weight * len(query_tokens & field_tokens)

        if score > 0:
            scored.append((score, listing))

    # Highest score first; stable sort preserves dataset order for ties.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    client = _get_groq_client()
    item_desc = _describe_item(new_item)
    items = wardrobe.get("items", []) if wardrobe else []

    system_prompt = (
        "You are a thoughtful personal stylist for secondhand fashion. "
        "Keep suggestions concise, specific, and practical. Use plain text "
        "(no markdown headers), and aim for 1–2 outfit ideas."
    )

    if not items:
        # Empty wardrobe → general styling advice instead of named pieces.
        user_prompt = (
            f"Someone is considering buying this thrifted item:\n  {item_desc}\n\n"
            "They haven't told us what's in their closet yet. Suggest 1–2 outfit "
            "ideas built around this piece, describing the kinds of items that pair "
            "well with it (e.g. bottoms, shoes, layers) and the overall vibe it suits."
        )
    else:
        # Wardrobe present → suggest combinations naming specific owned pieces.
        wardrobe_lines = "\n".join(f"  - {_describe_item(it)}" for it in items)
        user_prompt = (
            f"Someone is considering buying this thrifted item:\n  {item_desc}\n\n"
            f"Here is what they already own:\n{wardrobe_lines}\n\n"
            "Suggest 1–2 complete outfits that combine the new item with specific "
            "pieces from their wardrobe. Name the wardrobe pieces you use and explain "
            "the vibe of each outfit in a sentence or two."
        )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: can't write a caption without an outfit.
    if not outfit or not outfit.strip():
        return "Can't write a fit card without an outfit suggestion."

    name = new_item.get("title") or new_item.get("name") or "this piece"
    price = new_item.get("price")
    platform = new_item.get("platform")

    details = [f"item name: {name}"]
    if price is not None:
        # Drop a trailing ".0" so captions read "$24" not "$24.0".
        price_str = f"{price:g}"
        details.append(f"price: ${price_str}")
    if platform:
        details.append(f"platform: {platform}")

    system_prompt = (
        "You write short, authentic OOTD captions for thrifted finds — the kind a "
        "real person posts on Instagram or TikTok. Casual and specific, not a product "
        "description. 2–4 sentences, plain text. Mention the item name, price, and "
        "platform naturally, once each. A tasteful emoji or two is fine."
    )
    user_prompt = (
        "Write a caption for this thrifted outfit.\n\n"
        f"Item details — {'; '.join(details)}\n\n"
        f"The outfit:\n{outfit.strip()}"
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=1.0,  # higher temp → captions vary across runs
    )
    return response.choices[0].message.content.strip()


# ── Stretch tool: refine_search ───────────────────────────────────────────────

def refine_search(parsed: dict) -> list[dict]:
    """
    Retry search_listings with progressively relaxed constraints when the
    original search returned nothing. Returns the first non-empty result, or
    an empty list if every relaxation is exhausted.

    Args:
        parsed: the parsed query dict {description, size, max_price, category}.

    Relaxation stages (least drastic first; stop at the first that finds items):
        1. drop the size filter   (keep price + category)
        2. drop the price ceiling (keep category)
        3. relax the category     (description only)

    Keyword broadening is intentionally omitted: search_listings keeps any
    listing matching ANY description token, so if the full description matches
    nothing, no single token would either.
    """
    description = parsed.get("description", "") or ""
    size = parsed.get("size")
    max_price = parsed.get("max_price")
    category = parsed.get("category")

    # Stage 1: drop size.
    if size is not None:
        results = search_listings(description, None, max_price, category)
        if results:
            return results

    # Stage 2: drop price (and size).
    if max_price is not None:
        results = search_listings(description, None, None, category)
        if results:
            return results

    # Stage 3: relax category (description only).
    if category is not None:
        results = search_listings(description, None, None, None)
        if results:
            return results

    return []
