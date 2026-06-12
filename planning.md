# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Keyword-searches the 40 mock secondhand listings for items matching the user's description, optionally narrowing by size, a maximum price, and a category. It is the agent's only way to discover real inventory.

**Input parameters:**
- `description` (str): keywords describing the desired item, e.g. `"vintage graphic tee"`. Compared against each listing's title, description, and style_tags.
- `size` (str | None): size to filter by, matched case-insensitively as a substring so `"M"` matches `"S/M"`. `None` skips size filtering.
- `max_price` (float | None): inclusive price ceiling. `None` skips price filtering.
- `category` (str | None): one of `tops` / `bottoms` / `outerwear` / `shoes` / `accessories` to restrict results to that item type. `None` skips category filtering. Prevents a color/keyword match in the wrong category (e.g. a "white shirt" query returning "Off-White" sneakers).

**What it returns:**
A `list[dict]` of matching listings, sorted by relevance (best match first). Each listing dict contains: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, `platform`. Returns an empty list when nothing matches.

**What happens if it fails or returns nothing:**
It never raises — it returns `[]`. The planning loop reacts to the empty list by calling the stretch tool `refine_search` to retry with relaxed constraints. Only if that also returns nothing does the agent stop and report a helpful no-results message.

---

### Tool 2: suggest_outfit

**What it does:**
Uses the Groq LLM to propose 1–2 complete outfits that combine the thrifted item with pieces the user already owns, so the user can picture how the find fits into their closet.

**Input parameters:**
- `new_item` (dict): a listing dict (the item the user is considering buying) — the LLM is told its title, category, colors, and style_tags.
- `wardrobe` (dict): a wardrobe dict with an `items` key holding a list of wardrobe-item dicts (`name`, `category`, `colors`, `style_tags`, `notes`). May be empty.

**What it returns:**
A non-empty string describing 1–2 outfit ideas. When the wardrobe has items, the suggestions name specific pieces from it (e.g. "pair it with your baggy dark-wash jeans and chunky white sneakers").

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty, the tool does not error — it prompts the LLM for general styling advice for the item (what kinds of pieces pair well, what vibe it suits) and returns that instead.

---

### Tool 3: create_fit_card

**What it does:**
Uses the Groq LLM (at a higher temperature for variety) to turn an outfit idea into a short, shareable OOTD caption for Instagram/TikTok.

**Input parameters:**
- `outfit` (str): the outfit suggestion string returned by `suggest_outfit`.
- `new_item` (dict): the listing dict for the thrifted item, used so the caption can name the item, its price, and platform.

**What it returns:**
A 2–4 sentence caption string. It feels casual and authentic, captures the outfit's vibe in specific terms, and mentions the item name, price, and platform once each.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive error message string (e.g. "Can't write a fit card without an outfit suggestion.") rather than raising an exception.

---

### Additional Tools (if any)

### Stretch Tool: refine_search

**What it does:**
When `search_listings` finds nothing, this tool relaxes the search constraints in stages and re-runs the search, so a too-specific query doesn't dead-end the user. It is what makes the planning loop agentic — the agent decides to retry rather than giving up immediately.

**Input parameters:**
- `parsed` (dict): the parsed query fields (`description`, `size`, `max_price`, `category`) from the original attempt. The tool reads these and re-runs `search_listings` with some of them dropped.

**What it returns:**
A `list[dict]` of listings (same shape as `search_listings`), possibly still empty if every relaxation has been exhausted.

**Relaxation stages (applied in order, stopping at the first that returns results):**
1. Drop the `size` filter (keep price + category).
2. Remove the `max_price` ceiling (keep category).
3. Relax the `category` filter — search on `description` alone.

*(Keyword-broadening is intentionally not a stage: `search_listings` keeps any listing matching ANY description token, so if the full description matches nothing, no single token would either.)*

**What happens if it fails or returns nothing:**
If all stages are exhausted and still nothing matches, it returns `[]`; the planning loop then sets `session["error"]` to a helpful message suggesting the user broaden their request.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is linear with a single retry branch, and every decision is driven by whether the previous step produced a non-empty result:

1. **Parse** the query (LLM parse with regex fallback — see State Management) into `description`, `size`, `max_price`.
2. **Search:** call `search_listings`. If it returns results, continue to step 4.
3. **Refine (branch):** if the search was empty, call `refine_search` to retry with relaxed constraints. If it now returns results, continue. If it is still empty, set `session["error"]` and **stop** — do not call the LLM tools with empty input.
4. **Select** the top (most relevant) listing as `selected_item`.
5. **Suggest:** call `suggest_outfit(selected_item, wardrobe)`.
6. **Caption:** call `create_fit_card(outfit_suggestion, selected_item)`.
7. **Done:** return the session. The loop knows it's finished when the fit card is produced, or earlier if the error branch was taken.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session()` in `agent.py`) is the source of truth for the whole interaction. Each step writes its output into the dict; the next step reads what it needs from the dict rather than receiving loose variables.

Tracked fields:
- `query` — the raw user query.
- `parsed` — `{description, size, max_price, category}` extracted by the parser. **Parsing approach: LLM parse (Groq JSON mode) with a regex fallback.** The model extracts `description` (the item the user actually wants to buy — explicitly excluding pieces they say they already own or wear), `size`, `max_price`, and `category` (one of the five dataset categories, or `None` if unclear — validated against the allowed set). This handles conversational, multi-clause queries (e.g. "I wear shorts, I want a button shirt under $40" → `description: "button shirt"`), which a pure-regex parser gets wrong by leaking "shorts" into the search; the `category` lets `search_listings` keep a "shirt" request from returning shoes. The trade-off is one extra API call per query; in exchange we get reliable intent extraction. A deterministic regex parser (price/size patterns + leftover-as-description, `category` left `None`) remains as a fallback that runs only if the LLM call errors or returns malformed JSON, so the agent never crashes.
- `search_results` — the list returned by `search_listings` (or `refine_search`).
- `selected_item` — the top result, passed into both `suggest_outfit` and `create_fit_card`.
- `wardrobe` — the wardrobe dict chosen in the UI.
- `outfit_suggestion` — the string from `suggest_outfit`.
- `fit_card` — the string from `create_fit_card`.
- `error` — `None` on success; set to a message string if the interaction ended early.

`app.py`'s `handle_query` calls `run_agent`, then maps the finished session to the three UI panels. If `session["error"]` is not `None`, it shows the error in panel 1 and leaves the other two panels empty.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Call `refine_search` to retry with relaxed constraints; if it still returns nothing, set `session["error"]` to a helpful "try broadening your search" message and stop before the LLM tools. |
| suggest_outfit | Wardrobe is empty | Don't error — prompt the LLM for general styling advice for the item and return that string. |
| create_fit_card | Outfit input is missing or incomplete | Guard against an empty/whitespace `outfit`; return a descriptive error caption string instead of raising. |
| refine_search (stretch) | All relaxation stages exhausted, still no match | Return `[]`; the loop reports the no-results error to the user. |

---

## Architecture

```
User query + wardrobe choice
   │
   ▼
Planning Loop ────────────────────────────────────────────────────┐
   │                                                               │
   │   parse_query(query) ──→ session.parsed =                     │
   │        │               {description, size, max_price, category}│
   │        ▼                                                       │
   ├─▶ search_listings(description, size, max_price, category)      │
   │        │                                                       │
   │        ├─ results=[] ──▶ refine_search(parsed)                 │
   │        │                      │                                │
   │        │                      ├─ still [] ──▶ [ERROR]          │
   │        │                      │     session.error =            │
   │        │                      │     "No listings found…" ──────┤
   │        │                      │                                │
   │        │      results=[item,…] ◀─┘ (relaxed match)             │
   │        ▼                                                       │
   │   session.selected_item = results[0]                           │
   │        │                                                       │
   ├─▶ suggest_outfit(selected_item, wardrobe)                      │
   │        │     (empty wardrobe → general styling advice)         │
   │        ▼                                                       │
   │   session.outfit_suggestion = "…"                              │
   │        │                                                       │
   ├─▶ create_fit_card(outfit_suggestion, selected_item)            │
   │        │     (empty outfit → error caption string)             │
   │        ▼                                                       │
   │   session.fit_card = "…"                                       │
   │        │                                          error path ──┘
   ▼        ▼                                          returns here
Return session ──→ app.py maps session → 3 UI panels
   success:  [ Top listing ] [ Outfit idea ] [ Your fit card ]
   error:    error message fills panel 1; panels 2 & 3 empty
```

---

## AI Tool Plan

**AI tool used: Claude Code** (Anthropic's CLI). I direct it section-by-section from this planning.md so the generated code matches my spec, and I verify each piece before moving on.

**Milestone 3 — Individual tool implementations:**
I'll implement and verify the tools one at a time, never all at once.
- Give Claude Code the **Tool 1** section (inputs, return shape, failure mode) and ask it to implement `search_listings`, reusing `load_listings()` from `utils/data_loader.py`. Verify against ~3 queries: a normal match ("vintage graphic tee"), a size+price filter, and a guaranteed miss ("designer ballgown size XXS under $5") — confirm the miss returns `[]` and doesn't raise.
- Give Claude Code the **Tool 2** section and have it implement `suggest_outfit` with the Groq client. Verify with a real wardrobe (suggestions name specific pieces) and with the empty wardrobe (returns general advice, not an error).
- Give Claude Code the **Tool 3** section for `create_fit_card`. Verify the caption is 2–4 sentences and mentions item name, price, and platform; pass an empty `outfit` to confirm it returns the guard message.
- Give Claude Code the **Stretch Tool** section for `refine_search` and verify a too-narrow query now yields results after relaxation.

I won't trust generated code until it passes these checks against my spec.

**Milestone 4 — Planning loop and state management:**
- Give Claude Code the **Planning Loop**, **State Management**, and **Architecture** sections and have it implement `run_agent` in `agent.py`, writing each step's output into the `session` dict and taking the `refine_search` / error branch as drawn.
- Then have it implement `handle_query` in `app.py` to map the finished session to the three panels (error → panel 1).
- Verify end-to-end with `python agent.py` (happy path prints a found item + outfit + fit card; no-results path prints the error message) and `python app.py` (submit the example queries in the UI, including the deliberate no-results one).

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse.**
`handle_query` passes the query and the selected example wardrobe to `run_agent`, which initializes the session and parses the query with the Groq LLM (regex fallback). The LLM keys on the *wanted* item and ignores the "I mostly wear baggy jeans and chunky sneakers" clause: `description = "vintage graphic tee"`, `max_price = 30.0`, `size = None`, `category = "tops"`. Stored in `session["parsed"]`.

**Step 2 — Search.**
`search_listings("vintage graphic tee", size=None, max_price=30.0, category="tops")` scores listings by keyword overlap and price, restricted to tops. It returns matches led by **lst_006 — "Graphic Tee — 2003 Tour Bootleg Style," $24, depop, size L**. Results are stored in `session["search_results"]`; because the list is non-empty, the loop skips `refine_search`.

**Step 3 — Select.**
The top result, lst_006, is stored as `session["selected_item"]`.

**Step 4 — Suggest outfit.**
`suggest_outfit(lst_006, example_wardrobe)` calls Groq. Because the wardrobe has items, it returns specific combinations, e.g. "Wear the bootleg tour tee with your baggy dark-wash jeans and chunky white sneakers for an easy streetwear fit; layer the vintage black denim jacket over it when it's cooler." Stored in `session["outfit_suggestion"]`.

**Step 5 — Create fit card.**
`create_fit_card(outfit_suggestion, lst_006)` calls Groq at higher temperature and returns a caption mentioning the item, its $24 price, and depop, e.g. "Found my new favorite tee 🎸 this 2003 bootleg tour graphic ($24 on depop) with baggy jeans and chunky sneakers is the whole vibe. Throwing my black denim jacket on top when it gets cold. Thrift wins again." Stored in `session["fit_card"]`.

**Final output to user:**
The three UI panels show: **Top listing** — the formatted lst_006 details (title, price, platform, size, condition); **Outfit idea** — the styling suggestion from Step 4; **Your fit card** — the caption from Step 5. `session["error"]` is `None`, so no error panel is shown.
