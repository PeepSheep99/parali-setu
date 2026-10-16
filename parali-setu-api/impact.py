"""Deterministic impact of stubble collected instead of burned.

Every number shown to a user about emissions or savings comes from here --
never from Gemini. Factors are per tonne of straw diverted from open burning.

Method notes (also stated on the landing page and in the README):
- CO2 released by burning straw is biogenic (the plant absorbed it that
  season), so under IPCC convention it is NOT counted as avoided GHG.
  Only methane and nitrous oxide from burning are counted.
- Coal displacement applies only when the buyer burns the straw in place of
  coal (pellet co-firing, boilers). It is reported separately and never
  added to the headline.
- Ranges are carried where sources disagree; the point value is used for
  totals and the range is shown alongside.
"""
from __future__ import annotations

from scheduler import STRAW_T_PER_ACRE

# Gadde et al. 2009, emission factors for rice straw open-field burning
# (India / Thailand / Philippines), kg per tonne of straw burned.
CH4_KG_PER_T = 5.82
N2O_KG_PER_T = 0.1
CO_KG_PER_T = 102.0
# PM2.5 field-burning factor, kg/t; reported range 4.7-20 depending on
# spread vs pile burning (Pearl River Delta lab study; SE Asia review).
PM25_KG_PER_T = 8.3
PM25_KG_PER_T_RANGE = (4.7, 20.0)

# IPCC AR6 100-year global warming potentials.
GWP_CH4 = 27.0     # non-fossil methane
GWP_N2O = 273.0

# Conditional: straw (~14 MJ/kg) replacing Indian thermal coal (~20 MJ/kg,
# ~1.9 t CO2 per t coal) => ~0.7 t coal and ~1.33 t CO2 per t straw.
COAL_CO2_T_PER_T_STRAW = 1.33

# Farmer's avoided cost of clearing the field (baling, loading, transport),
# Rs per acre, Tribune reporting.
CLEARING_COST_INR_PER_ACRE_RANGE = (2500, 4000)

METHOD_NOTE = (
    "Avoided greenhouse gas counts only methane and nitrous oxide from burning "
    "(Gadde et al. 2009 factors, IPCC AR6 GWP100). CO2 from burning straw is biogenic "
    "and is not counted. Coal displacement is shown separately and applies only when "
    "the buyer replaces coal."
)


def non_co2_ghg_t_co2e_per_t() -> float:
    return (CH4_KG_PER_T * GWP_CH4 + N2O_KG_PER_T * GWP_N2O) / 1000


def impact_for_tonnes(tonnes: float, coal_replacing: bool = False) -> dict:
    tonnes = max(0.0, tonnes)
    acres = tonnes / STRAW_T_PER_ACRE
    low, high = CLEARING_COST_INR_PER_ACRE_RANGE
    return {
        "tonnes_diverted": round(tonnes, 3),
        "acres_cleared": round(acres, 2),
        "ghg_avoided_t_co2e": round(tonnes * non_co2_ghg_t_co2e_per_t(), 3),
        "pm25_avoided_kg": round(tonnes * PM25_KG_PER_T, 1),
        "pm25_avoided_kg_range": [round(tonnes * PM25_KG_PER_T_RANGE[0], 1), round(tonnes * PM25_KG_PER_T_RANGE[1], 1)],
        "co_avoided_kg": round(tonnes * CO_KG_PER_T, 1),
        "coal_displacement_t_co2": round(tonnes * COAL_CO2_T_PER_T_STRAW, 3) if coal_replacing else None,
        "farmer_clearing_cost_avoided_inr_range": [round(acres * low), round(acres * high)],
        "method": METHOD_NOTE,
    }


def impact_for_kg(kg: float, coal_replacing: bool = False) -> dict:
    return impact_for_tonnes(kg / 1000, coal_replacing)


# Punjab paddy straw generated per season: ~19.7 Mt from ~3.2 Mha of paddy
# (State of Punjab status report to the NGT, OA 632/2023).
PUNJAB_PADDY_STRAW_T = 19_700_000


def punjab_scenario(share_pct: float) -> dict:
    """Impact if `share_pct` percent of Punjab's paddy straw were collected
    through Parali Setu instead of burned. A what-if, labelled as such."""
    share_pct = min(max(share_pct, 0.0), 100.0)
    return {"share_pct": share_pct, **impact_for_tonnes(PUNJAB_PADDY_STRAW_T * share_pct / 100),
            "basis": "Share of Punjab's ~19.7 Mt paddy straw (NGT status report, State of Punjab)."}
