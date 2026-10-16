import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impact import impact_for_kg, impact_for_tonnes, non_co2_ghg_t_co2e_per_t  # noqa: E402


def test_non_co2_factor_matches_the_published_method():
    # 5.82 kg CH4 x 27 + 0.1 kg N2O x 273 = 184.44 kg CO2e per tonne
    assert round(non_co2_ghg_t_co2e_per_t(), 5) == 0.18444


def test_one_acre_of_paddy_straw():
    result = impact_for_tonnes(1.75)
    assert result["acres_cleared"] == 1.0
    assert result["ghg_avoided_t_co2e"] == round(1.75 * 0.18444, 3)
    assert result["co_avoided_kg"] == 178.5
    assert result["farmer_clearing_cost_avoided_inr_range"] == [2500, 4000]


def test_coal_displacement_is_separate_and_conditional():
    assert impact_for_tonnes(10)["coal_displacement_t_co2"] is None
    with_coal = impact_for_tonnes(10, coal_replacing=True)
    assert with_coal["coal_displacement_t_co2"] == 13.3
    assert with_coal["ghg_avoided_t_co2e"] == impact_for_tonnes(10)["ghg_avoided_t_co2e"], (
        "coal displacement must never be folded into the headline GHG figure")


def test_kg_helper_and_negative_input():
    assert impact_for_kg(1750)["acres_cleared"] == 1.0
    assert impact_for_tonnes(-3)["tonnes_diverted"] == 0.0
