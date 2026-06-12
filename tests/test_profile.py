"""
Tests for the style profile memory (stretch feature). Uses tmp_path so the
real data/style_profile.json is never touched.
"""

from utils import profile


def test_load_profile_missing_returns_default(tmp_path):
    path = str(tmp_path / "nope.json")
    p = profile.load_profile(path)
    assert p["wardrobe"] == {"items": []}
    assert "preferences" in p


def test_save_then_load_round_trip(tmp_path):
    path = str(tmp_path / "profile.json")
    p = profile.load_profile(path)
    p["wardrobe"] = {"items": [{"id": "w1", "name": "Baggy jeans"}]}
    profile.save_profile(p, path)

    reloaded = profile.load_profile(path)
    assert reloaded["wardrobe"]["items"][0]["name"] == "Baggy jeans"


def test_load_corrupt_file_returns_default(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json")
    p = profile.load_profile(str(path))
    assert p["wardrobe"] == {"items": []}


def test_update_preferences_accumulates():
    p = profile._default_profile()
    profile.update_preferences(p, {"description": "vintage graphic tee",
                                   "size": "M", "max_price": 30.0, "category": "tops"})
    profile.update_preferences(p, {"description": "denim jacket",
                                   "size": "L", "max_price": None, "category": "outerwear"})
    prefs = p["preferences"]
    assert prefs["last_size"] == "L"          # latest wins
    assert prefs["last_max_price"] == 30.0    # kept (second query had no price)
    assert set(prefs["categories"]) == {"tops", "outerwear"}
    assert "vintage" in prefs["styles"] and "denim" in prefs["styles"]
