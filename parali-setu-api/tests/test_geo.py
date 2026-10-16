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
