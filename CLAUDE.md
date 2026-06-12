# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FitFindr is a thrift-shopping AI agent that takes a user's style query, searches mock secondhand listings, suggests an outfit using the user's wardrobe, and generates a social media caption. It uses a Groq-powered LLM and a Gradio web UI.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file with your Groq API key:
```
GROQ_API_KEY=your_key_here
```

Get a free key at [console.groq.com](https://console.groq.com).

## Running

```bash
python app.py        # Launch Gradio UI at http://localhost:7860
python agent.py      # Run CLI tests for the planning loop
python utils/data_loader.py  # Verify data loads correctly
```

## Testing

```bash
pytest               # Run all tests
pytest tests/test_tools.py  # Run a specific test file
```

## Architecture

The project has three layers that must be implemented (stubs are already in place):

**`tools.py` — Three LLM-backed tools:**
- `search_listings(description, size, max_price)` — keyword-filters the 40 mock listings in `data/listings.json`, returns list of matching dicts sorted by relevance; returns empty list on no match (never raises)
- `suggest_outfit(new_item, wardrobe)` — calls Groq to generate 1-2 outfit ideas combining the thrifted item with the user's existing wardrobe; handles empty wardrobe gracefully
- `create_fit_card(outfit, new_item)` — calls Groq at higher temperature to write a 2-4 sentence Instagram/TikTok caption mentioning item name, price, and platform

**`agent.py` — Planning loop (`run_agent(query, wardrobe)`):**
Orchestrates the three tools in sequence: parse query → `search_listings` → pick top result → `suggest_outfit` → `create_fit_card`. Uses a session state dict (initialized by `_new_session()`) to track results. Returns the session dict or an error-state dict on failure (no-results is a valid non-error path that returns a "no results" message).

**`app.py` — Gradio UI:**
The `handle_query()` function (the main TODO) receives the user's text query and wardrobe selection, calls `run_agent()`, and maps the session dict to three output panels: top listing found, outfit idea, and fit card.

**Data:**
- `data/listings.json` — 40 mock items with fields: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`
- `data/wardrobe_schema.json` — wardrobe item schema plus an example 10-item wardrobe; `utils/data_loader.py` exposes `load_listings()` and `load_example_wardrobe()`

## Groq Client

The Groq client is initialized in `tools.py` (and `agent.py` for query parsing). Use model `llama-3.3-70b-versatile` (or whichever is configured). The client reads `GROQ_API_KEY` from `.env` via `python-dotenv`.
