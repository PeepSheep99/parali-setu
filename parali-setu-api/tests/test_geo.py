import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo import DISTRICT_ALIASES, DISTRICT_COORDS, district_from_text, nearest_district  # noqa: E402


def test_districts_are_recognised_in_english_hindi_and_punjabi():
    assert district_from_text("near Patiala") == "Patiala"
    assert district_from_text("ਸੰਗਰੂਰ ਵਿੱਚ") == "Sangrur"
    assert district_from_text("करनाल ज़िला") == "Karnal"
    assert district_from_text("Bhatinda") == "Bathinda"
    assert district_from_text("Amritsar") is None


def test_every_district_has_aliases_and_coordinates():
    assert set(DISTRICT_ALIASES) == set(DISTRICT_COORDS)
    for name, (lat, lon) in DISTRICT_COORDS.items():
        assert nearest_district(lat, lon) == name


def test_the_demo_farm_is_always_in_reach_and_stable_per_farmer():
    from geo import DISTRICT_COORDS, demo_farm_location
    from pickups import road_km
    lat, lon, name = demo_farm_location(None, "farmer_a")
    assert name == "Sangrur" and road_km(lat, lon, *DISTRICT_COORDS["Sangrur"]) < 15
    assert demo_farm_location("Patiala", "farmer_a") == demo_farm_location("Patiala", "farmer_a")
    assert demo_farm_location("Patiala", "farmer_a")[2] == "Patiala"
