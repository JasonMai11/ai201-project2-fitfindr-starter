# FitFindr — Starter Kit

This starter kit contains everything you need to begin Project 2.

## What's Included

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── utils/
│   └── data_loader.py         # Helper functions for loading the data
├── tools.py                   # The 3 required tools + refine_search (stretch)
├── agent.py                   # Query parsing + run_agent planning loop
├── app.py                     # Gradio web UI (handle_query)
├── tests/test_tools.py        # Tool tests (incl. one per failure mode)
├── tests/test_agent.py        # parse_query tests (LLM + regex fallback)
├── planning.md                # Design spec (tools, loop, diagram)
└── requirements.txt           # Python dependencies
```

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## The Mock Listings Dataset

`data/listings.json` contains 40 mock secondhand listings across categories (tops, bottoms, outerwear, shoes, accessories) and styles (vintage, y2k, grunge, cottagecore, streetwear, and more).

Each listing has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`.

Load it with:
```python
from utils.data_loader import load_listings
listings = load_listings()
```

## The Wardrobe Schema

`data/wardrobe_schema.json` defines the format your agent uses to represent a user's existing wardrobe. It includes:

- `schema`: field definitions for a wardrobe item
- `example_wardrobe`: a sample wardrobe with 10 items you can use for testing
- `empty_wardrobe`: a starting template for a new user

Load an example wardrobe with:
```python
from utils.data_loader import get_example_wardrobe
wardrobe = get_example_wardrobe()
```

## Where to Start

1. **Read `planning.md` and fill it out before writing any code.**
2. Verify the data loads correctly by running `python utils/data_loader.py`.
3. Build and test each tool individually before connecting them through your planning loop.

Your implementation files go in this same directory. There's no required file structure for your agent code — organize it however makes sense for your design.

---

# FitFindr — Implementation

FitFindr takes a natural-language request for a secondhand clothing item, finds a
matching listing, suggests an outfit that combines it with the user's existing
wardrobe, and writes a shareable "fit card" caption.

## Running

```bash
pip install -r requirements.txt          # install deps
echo "GROQ_API_KEY=your_key_here" > .env # free key at console.groq.com

python app.py                            # launch the web UI (http://127.0.0.1:7860)
python agent.py                          # CLI smoke test (happy + no-results paths)
python -m pytest tests/                  # run the test suite
```

## Tool Inventory

The agent uses four tools. The first three are required; `refine_search` is a stretch tool.

### `search_listings` — find matching listings
- **Inputs:** `description: str` (keywords), `size: str | None = None`, `max_price: float | None = None`, `category: str | None = None` (one of `tops`/`bottoms`/`outerwear`/`shoes`/`accessories`).
- **Output:** `list[dict]` of listings sorted by relevance (best first); `[]` if nothing matches. Never raises.
- **Purpose:** the agent's only way to discover inventory. Scores listings by weighted keyword overlap (title ×3, style_tags/category ×2, description/brand/colors ×1) after filtering by size, price, and category.

### `suggest_outfit` — style the find with the user's wardrobe
- **Inputs:** `new_item: dict` (a listing), `wardrobe: dict` (has an `items` list; may be empty).
- **Output:** `str` — 1–2 outfit ideas. With a wardrobe, it names specific owned pieces.
- **Purpose:** help the user picture how the thrifted item fits their closet. Calls the Groq LLM (`llama-3.3-70b-versatile`).

### `create_fit_card` — write a shareable caption
- **Inputs:** `outfit: str` (from `suggest_outfit`), `new_item: dict` (the listing).
- **Output:** `str` — a 2–4 sentence OOTD caption mentioning the item name, price, and platform.
- **Purpose:** turn the outfit into social-post copy. Calls the LLM at high temperature so captions vary across runs.

### `refine_search` — relax constraints when nothing matches (stretch)
- **Inputs:** `parsed: dict` (`description`, `size`, `max_price`, `category`).
- **Output:** `list[dict]` — first non-empty result after relaxing, or `[]` if exhausted.
- **Purpose:** keep a too-narrow query from dead-ending. Relaxes in stages: **drop size → drop price → relax category**.

## Planning Loop

`run_agent(query, wardrobe)` in `agent.py` runs a linear loop with one retry branch; each step's decision depends on whether the previous step produced a non-empty result:

1. **Parse** the query into `{description, size, max_price, category}` (see State Management).
2. **Search** with `search_listings`. If it returns results, go to step 4.
3. **Refine (branch):** if the search was empty, call `refine_search`. If still empty, set `session["error"]` and stop — never call the LLM tools on empty input.
4. **Select** the top (most relevant) result as `selected_item`.
5. **Suggest** an outfit with `suggest_outfit`.
6. **Caption** it with `create_fit_card`.
7. **Return** the session.

## State Management

A single `session` dict (from `_new_session()`) is the source of truth for one
interaction. Each step writes its output into the dict; the next step reads from
it rather than passing loose variables. Fields: `query`, `parsed`,
`search_results`, `selected_item`, `wardrobe`, `outfit_suggestion`, `fit_card`,
`error`. `app.py`'s `handle_query` maps the finished session to the three UI
panels; a non-`None` `error` short-circuits to panel 1.

**Query parsing:** the LLM (Groq JSON mode) extracts the four parsed fields,
keying on the item the user *wants* (not pieces they say they already own/wear)
and tagging a `category`. A deterministic regex parser is the fallback if the LLM
call errors or returns malformed JSON, so the agent never crashes.

## Error Handling (per tool)

Each tool owns its failure mode, so the loop needs no `try/except` wrapper. Examples below are real outputs observed during testing.

| Tool | Failure mode | Behavior | Concrete example from testing |
|------|--------------|----------|-------------------------------|
| `search_listings` | No match | returns `[]` (no exception) | `search_listings("designer ballgown", size="XXS", max_price=5)` → `[]` (`test_search_empty_results`) |
| `suggest_outfit` | Empty wardrobe | general styling advice, not an error | empty wardrobe + graphic tee → "…pair it with high-waisted jeans and black combat boots…" (general advice, no owned pieces named) |
| `create_fit_card` | Empty/whitespace outfit | descriptive error string, no LLM call | `create_fit_card("", item)` → `"Can't write a fit card without an outfit suggestion."` (`test_create_fit_card_empty_outfit`) |
| `refine_search` | All stages exhausted | returns `[]`; loop reports a helpful no-results message | `refine_search({"description":"designer ballgown", ...})` → `[]` (`test_refine_search_exhausted_returns_empty`) |

End-to-end, the no-results path surfaces to the user as:
`"No listings matched 'designer ballgown'. Try fewer keywords, a higher price, or removing the size filter."`

## Spec Reflection

The implementation follows `planning.md`, with three changes made during development as real queries exposed gaps:

- **Query parsing: regex → LLM (with regex fallback).** The spec originally chose pure regex parsing. The query *"I wear shorts, I want a button shirt under $40"* leaked "shorts" into the search and returned shorts instead of a shirt — regex can't separate "what I want" from "what I wear." Switched to LLM parsing (the stub explicitly allows it) and updated `planning.md` to match; kept the regex as a fallback for robustness.
- **Added a `category` filter.** *"white shirt"* then returned off-white *sneakers*, because the color word "white" in a shoe's title outscored matching the item type. The LLM now tags a `category` and `search_listings` filters by it, so a shirt request can't return shoes. This was a *ranking* bug, distinct from the no-results case `refine_search` handles.
- **`refine_search` simplified.** The spec listed `refine_search(parsed, attempted)` with a "broaden keywords" stage. The `attempted` parameter proved unnecessary (a single call walks all stages), and keyword-broadening is a no-op for our OR-based scorer (if the full description matches nothing, no single token would either). Final stages: drop size → drop price → relax category. `planning.md` was corrected to reflect this.

The tool contracts, the linear-loop-with-retry-branch, the session-dict state model, and the per-tool error handling all matched the spec as written.

## AI Usage

**Instance 1 — Implementing `search_listings` from the Tool 1 spec.**
- *Input:* the Tool 1 section of `planning.md` (parameter names/types, the relevance-sorted-list return, the "empty list, never raise" failure mode) plus the instruction to reuse `load_listings()`.
- *Produced:* a keyword-overlap scorer with field weighting and a `_tokenize` helper.
- *What I changed/decided:* I made the **blank-description** case return `[]` (strict, matching the "drop score 0" rule) rather than returning all size/price-filtered items, and I verified the output against three queries (normal match, size+price filter, guaranteed miss) before trusting it.

**Instance 2 — The query diagram + loop, and overriding the parsing decision.**
- *Input:* the Architecture diagram and the Planning Loop / State Management sections of `planning.md`, then later the failing query and my diagnosis of why it returned the wrong item.
- *Produced:* the `run_agent` loop wired to the session dict, and (on the second pass) an LLM-based `parse_query`.
- *What I overrode:* the spec said regex parsing — I **overrode that decision**, switched to LLM parsing to fix the want-vs-wear confusion, and **added a regex fallback** that wasn't in the original spec so the agent can't crash if the API fails. I then updated `planning.md` so the spec and code stayed in sync.

**Instance 3 — Tests with a mocked LLM.**
- *Input:* the Error Handling table from `planning.md` (one test per failure mode) and the existing tool signatures.
- *Produced:* `tests/` with a fake Groq client fixture so the LLM-backed tools are tested offline.
- *What I changed:* I had it patch the client at the correct module boundary (`agent._get_groq_client` vs `tools._get_groq_client`) and assert on the *prompt that was sent* (e.g. that an empty wardrobe takes the general-advice branch), rather than just checking the return value.
