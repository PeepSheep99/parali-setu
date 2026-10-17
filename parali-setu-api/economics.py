"""Break-even, from both sides of the trade.

Company: a forward order from us, against what a plant does today -- buy the
year's straw in the six-week harvest rush at the in-season price and store it
itself. Farmer: booking us, against hiring a baler or burning.

Every constant is SOURCED (with where) or ASSUMPTION, as in costs.py. The
comparison is shown even when it does not favour us: at sourced figures our
price per tonne is close to buying at harvest and storing, and the case for a
contract rests on the cash a plant doesn't tie up, the straw it doesn't lose
in storage, and supply it can count on.
"""
from __future__ import annotations

from costs import HIRED_BALING_PER_ACRE_INR, IN_SEASON_DELIVERED_PER_T_INR, STORAGE_PER_T_MONTH_INR
from scheduler import STRAW_T_PER_ACRE

# SOURCED: companies storing paddy straw in Punjab lose about 15-25% of it a
# year (rain, rot, fire). CEEW, "How Can Paddy Straw Storage Solutions Boost
# Biomass Supply Chain?" (survey of Punjab biomass companies).
STORAGE_LOSS_PER_YEAR = (0.15, 0.25)
# SOURCED: five of the eight companies CEEW surveyed had a fire in storage.
STORAGE_FIRE_SHARE = (5, 8)
# SOURCED: a biomass plant executive put the plants' actual cost of straw at
# Rs 300 per quintal, against the Rs 169 paid for it (Tribune, 19 Sep 2024).
PLANT_STATED_COST_PER_T_INR = 3000.0
# ASSUMPTION: what a plant pays for working capital (paying for the whole
# year's straw at harvest), a year.
WORKING_CAPITAL_RATE = 0.10
# ASSUMPTION: what our covered, fire-watched stacks lose a year. Our quote does
# not yet include it; shown as the margin it would cost us.
OUR_STORAGE_LOSS_PER_YEAR = 0.05

# SOURCED: environmental compensation per stubble-burning incident, doubled
# by MoEFCC notification G.S.R. 690(E), 6 Nov 2024: under 2 acres Rs 5,000,
# 2-5 acres Rs 10,000, over 5 acres Rs 30,000.
BURNING_FINE_INR = ((2, 5000), (5, 10000), (float("inf"), 30000))
# SOURCED (as the landing page states it): burning costs a farmer about Rs 500
# an acre and a day.
BURNING_COST_PER_ACRE_INR = 500


def company_case(quote: dict, tonnes_per_month: float, months: int, months_in_storage: float) -> dict:
    """Our delivered price against buying the same usable straw at harvest
    and storing it in the plant's own yard, per tonne and over the contract."""
    total_t = tonnes_per_month * months
    hold = months_in_storage
    ours = quote["price_per_t"]

    def diy(loss_per_year: float) -> dict:
        lost = loss_per_year * hold / 12                     # share of stored straw lost by the time it is used
        buy_t = 1 / (1 - lost)                               # bought per usable tonne
        price = IN_SEASON_DELIVERED_PER_T_INR * buy_t
        storage = STORAGE_PER_T_MONTH_INR * hold * buy_t
        interest = price * WORKING_CAPITAL_RATE * hold / 12
        per_t = price + storage + interest
        return {"loss_pct": round(100 * lost, 1), "buy_per_usable_t": round(buy_t, 3),
                "price_per_t": round(price), "storage_per_t": round(storage), "interest_per_t": round(interest),
                "per_usable_t": round(per_t), "contract_inr": round(per_t * total_t)}

    low, high = diy(STORAGE_LOSS_PER_YEAR[0]), diy(STORAGE_LOSS_PER_YEAR[1])
    # Cash a plant pays out at harvest for the year (at the lower loss).
    upfront = round(IN_SEASON_DELIVERED_PER_T_INR * total_t / (1 - STORAGE_LOSS_PER_YEAR[0] * hold / 12))
    # What our own (covered) storage loss would cost per tonne, out of our margin.
    our_loss_cost = round(quote["cost_per_t"] * OUR_STORAGE_LOSS_PER_YEAR * hold / 12)
    return {
        "total_t": total_t, "months_in_storage": hold,
        "ours": {"per_t": ours, "contract_inr": round(ours * total_t), "paid": "monthly, on delivery",
                 "upfront_inr": 0},
        "buy_at_harvest": {"low_loss": low, "high_loss": high, "upfront_inr": upfront,
                           "fires_in_storage": f"{STORAGE_FIRE_SHARE[0]} of {STORAGE_FIRE_SHARE[1]} companies surveyed"},
        "saving_per_t": {"low": round(low["per_usable_t"] - ours), "high": round(high["per_usable_t"] - ours)},
        "saving_contract_inr": {"low": round((low["per_usable_t"] - ours) * total_t),
                                "high": round((high["per_usable_t"] - ours) * total_t)},
        "plant_stated_cost_per_t": PLANT_STATED_COST_PER_T_INR,
        "our_margin_per_t": quote["margin_per_t"],
        "our_storage_loss_per_t": our_loss_cost,
        "sources": {
            "in_season_price": "Tribune: plants pay Rs 169/quintal in season",
            "storage_loss": "CEEW survey of Punjab biomass companies: 15-25% a year",
            "plant_stated_cost": "Tribune, 19 Sep 2024: a plant executive puts actual cost at Rs 300/quintal",
            "assumptions": f"storage Rs {STORAGE_PER_T_MONTH_INR:.0f}/t a month (ours, applied to both); working capital "
                           f"{WORKING_CAPITAL_RATE:.0%} a year; our covered stacks lose {OUR_STORAGE_LOSS_PER_YEAR:.0%} a year",
        },
    }


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
