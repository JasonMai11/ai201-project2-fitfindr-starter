"""
Style profile memory (stretch feature).

Persists a user's wardrobe and accumulated style preferences to a JSON file so a
returning user doesn't have to re-describe their closet every session. All reads
are defensive — a missing or corrupt file yields a default empty profile rather
than raising.
"""

import json
import os

# Stored alongside the data files; created on first save.
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "style_profile.json")


def _default_profile() -> dict:
    return {
        "wardrobe": {"items": []},
        "preferences": {
            "last_size": None,
            "last_max_price": None,
            "categories": [],   # categories the user has searched for
            "styles": [],       # style keywords seen in descriptions
        },
    }


def load_profile(path: str = PROFILE_PATH) -> dict:
    """Load the saved profile, or a fresh default if none exists / it's unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Backfill any missing top-level keys so callers can rely on the shape.
        default = _default_profile()
        default.update({k: v for k, v in data.items() if k in default})
        if "items" not in default.get("wardrobe", {}):
            default["wardrobe"] = {"items": []}
        return default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default_profile()


def save_profile(profile: dict, path: str = PROFILE_PATH) -> None:
    """Write the profile to disk as JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)


def update_preferences(profile: dict, parsed: dict) -> dict:
    """
    Fold a parsed query into the profile's preferences: remember the latest size
    and price, and accumulate (deduped) categories and style keywords seen.
    Mutates and returns the profile.
    """
    prefs = profile.setdefault("preferences", _default_profile()["preferences"])

    if parsed.get("size"):
        prefs["last_size"] = parsed["size"]
    if parsed.get("max_price") is not None:
        prefs["last_max_price"] = parsed["max_price"]

    if parsed.get("category") and parsed["category"] not in prefs.setdefault("categories", []):
        prefs["categories"].append(parsed["category"])

    styles = prefs.setdefault("styles", [])
    for word in (parsed.get("description") or "").lower().split():
        word = word.strip(".,!?")
        if len(word) >= 3 and word not in styles:
            styles.append(word)

    return profile
