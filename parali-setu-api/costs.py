"""The money model: what a tonne of straw costs Parali Setu to buy, collect,
store and deliver, and what we quote a company for it.

Every constant is labelled SOURCED (with where it comes from) or ASSUMPTION
(our working figure, shown on the ops console so it can be challenged). The
honest headline: at today's in-season delivered price of about Rs 1,690/t,
buying, collecting and storing straw for year-round delivery is a thin or
negative margin. The business works only if collection is cheaper than what
farmers pay hired balers today, which is the job of the routing optimizer,
and if industry pays a premium for guaranteed year-round supply.
"""
from __future__ import annotations

from dataclasses import dataclass

from geo import haversine_km
from scheduler import ROAD_FACTOR, STRAW_T_PER_ACRE

# Farm-gate price we post to farmers, Rs/kg. Bounds decided by the team.
FARM_GATE_MIN_PER_KG = 0.5
FARM_GATE_MAX_PER_KG = 1.5
FARM_GATE_BASE_PER_KG = 0.6
# Share of the procurement LP's shadow price passed on to farmers.
SHADOW_PRICE_SHARE = 0.5

# SOURCED: farmers pay Rs 2,500-4,000 per acre to have straw baled and hauled
# (Tribune). At 1.75 t/acre that is Rs 1,430-2,290 per tonne.
HIRED_BALING_PER_ACRE_INR = (2500, 4000)
HIRED_BALING_PER_T_INR = tuple(round(x / STRAW_T_PER_ACRE) for x in HIRED_BALING_PER_ACRE_INR)
# ASSUMPTION: our own crews' cost per tonne (baling, loading, haul to depot),
# below the hired rate because routes are planned densely.
OWN_COLLECTION_PER_T_INR = 1100.0
# ASSUMPTION: an on-call crew, at the low end of the market rate.
PARTNER_COLLECTION_PER_T_INR = float(HIRED_BALING_PER_T_INR[0])
# ASSUMPTION: truck freight for baled straw, Rs per tonne-km of road.
HAUL_PER_T_KM_INR = 4.0
# ASSUMPTION: covered bale stack with fire watch, Rs per tonne per month.
STORAGE_PER_T_MONTH_INR = 60.0
# SOURCED: biomass plants pay about Rs 169 per quintal for delivered straw
# in season (Tribune), i.e. Rs 1,690 per tonne.
IN_SEASON_DELIVERED_PER_T_INR = 1690.0
DEFAULT_MARGIN_PCT = 10.0


def road_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_km(lat1, lon1, lat2, lon2) * ROAD_FACTOR


def haul_per_t(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return road_km(lat1, lon1, lat2, lon2) * HAUL_PER_T_KM_INR


def clamp_farm_gate(price_per_kg: float) -> float:
    return round(min(FARM_GATE_MAX_PER_KG, max(FARM_GATE_MIN_PER_KG, price_per_kg)), 2)


@dataclass(frozen=True)
class Quote:
    farm_gate_per_t: float
    collection_per_t: float
    storage_per_t: float
    haul_per_t: float
    margin_per_t: float

    @property
    def cost_per_t(self) -> float:
        return round(self.farm_gate_per_t + self.collection_per_t + self.storage_per_t + self.haul_per_t, 2)

    @property
    def price_per_t(self) -> float:
        return round(self.cost_per_t + self.margin_per_t, 2)

    def as_dict(self) -> dict:
        return {
            "farm_gate_per_t": self.farm_gate_per_t, "collection_per_t": self.collection_per_t,
            "storage_per_t": self.storage_per_t, "haul_per_t": self.haul_per_t,
            "cost_per_t": self.cost_per_t, "margin_per_t": self.margin_per_t, "price_per_t": self.price_per_t,
            "in_season_benchmark_per_t": IN_SEASON_DELIVERED_PER_T_INR,
        }


def quote(
    farm_gate_per_kg: float,
    partner_share: float,
    months_in_storage: float,
    depot: tuple[float, float],
    site: tuple[float, float],
    margin_pct: float = DEFAULT_MARGIN_PCT,
) -> Quote:
    """Delivered price per tonne for a customer, built up from costs. Every
    input is a number a person can check; nothing here is estimated by AI."""
    if not 0 <= partner_share <= 1:
        raise ValueError("partner_share must be in [0, 1]")
    if months_in_storage < 0 or margin_pct < 0:
        raise ValueError("months_in_storage and margin_pct must not be negative")
    farm_gate = round(farm_gate_per_kg * 1000)
    collection = round((1 - partner_share) * OWN_COLLECTION_PER_T_INR + partner_share * PARTNER_COLLECTION_PER_T_INR)
    storage = round(months_in_storage * STORAGE_PER_T_MONTH_INR)
    haul = round(haul_per_t(*depot, *site))
    cost = farm_gate + collection + storage + haul
    return Quote(farm_gate, collection, storage, haul, round(cost * margin_pct / 100))
