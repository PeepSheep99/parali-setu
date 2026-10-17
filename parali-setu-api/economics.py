"""What a farmer gains: one farm cleared three ways -- booking us, hiring a
baler, or burning.

Every constant is SOURCED (with where) or comes from costs.py, as there.
"""
from __future__ import annotations

from costs import HIRED_BALING_PER_ACRE_INR
from scheduler import STRAW_T_PER_ACRE

# SOURCED: environmental compensation per stubble-burning incident, doubled
# by MoEFCC notification G.S.R. 690(E), 6 Nov 2024: under 2 acres Rs 5,000,
# 2-5 acres Rs 10,000, over 5 acres Rs 30,000.
BURNING_FINE_INR = ((2, 5000), (5, 10000), (float("inf"), 30000))
# SOURCED (as the landing page states it): burning costs a farmer about Rs 500
# an acre and a day.
BURNING_COST_PER_ACRE_INR = 500


def burning_fine(acres: float) -> int:
    return next(fine for limit, fine in BURNING_FINE_INR if acres < limit or limit == float("inf"))


def farmer_case(acres: float, price_per_kg: float) -> dict:
    """One farm, three ways to clear it before sowing."""
    straw_t = round(acres * STRAW_T_PER_ACRE, 2)
    payout = round(straw_t * 1000 * price_per_kg)
    baler = (round(HIRED_BALING_PER_ACRE_INR[0] * acres), round(HIRED_BALING_PER_ACRE_INR[1] * acres))
    return {
        "acres": acres, "straw_t": straw_t, "price_per_kg": price_per_kg,
        "parali_setu": {"farmer_pays": 0, "farmer_gets": payout, "net": payout},
        "hire_baler": {"farmer_pays": baler, "net": (-baler[1], -baler[0])},
        "burn": {"farmer_pays": round(BURNING_COST_PER_ACRE_INR * acres), "fine_if_caught": burning_fine(acres),
                 "net": (-(round(BURNING_COST_PER_ACRE_INR * acres) + burning_fine(acres)), -round(BURNING_COST_PER_ACRE_INR * acres))},
        "better_than_baler": (payout + baler[0], payout + baler[1]),
        "sources": {"baler": "Tribune: Rs 2,500-4,000 an acre to bale and haul",
                    "fine": "MoEFCC G.S.R. 690(E), 6 Nov 2024: Rs 5,000 / 10,000 / 30,000 by farm size",
                    "straw": f"{STRAW_T_PER_ACRE} t of straw an acre (Hindustan Times: 17-18 quintals)"},
    }
