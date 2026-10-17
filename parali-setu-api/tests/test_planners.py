"""Business-model planners: cost model and quotes, procurement LP with
shadow-price posting, and the delivery LP with inventory carryover."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from costs import (  # noqa: E402
    FARM_GATE_BASE_PER_KG,
    FARM_GATE_MAX_PER_KG,
    FARM_GATE_MIN_PER_KG,
    HIRED_BALING_PER_T_INR,
    IN_SEASON_DELIVERED_PER_T_INR,
    OWN_COLLECTION_PER_T_INR,
    PARTNER_COLLECTION_PER_T_INR,
    STORAGE_PER_T_MONTH_INR,
    quote,
)
from deliveries import DepotStock, OrderLine, plan_deliveries  # noqa: E402
from geo import DISTRICT_COORDS  # noqa: E402
from procurement import Depot, DistrictSupply, SalesBook, plan_procurement, posted_price  # noqa: E402

SANGRUR = DISTRICT_COORDS["Sangrur"]
PATIALA = DISTRICT_COORDS["Patiala"]
BATHINDA = DISTRICT_COORDS["Bathinda"]


def depot(pid="dep_sangrur", where=SANGRUR, capacity=10_000, own=500, partner=300, radius=80):
    return Depot(pid, pid, where[0], where[1], capacity, own, partner, radius)


def supply(name="Sangrur", where=SANGRUR, weekly=(400, 600)):
    return DistrictSupply(name, where[0], where[1], tuple(weekly))


# ---- costs

def test_hired_rate_comes_from_the_per_acre_source():
    assert HIRED_BALING_PER_T_INR == (1429, 2286)
    assert OWN_COLLECTION_PER_T_INR < PARTNER_COLLECTION_PER_T_INR <= HIRED_BALING_PER_T_INR[1]


def test_quote_adds_up_and_shows_the_benchmark():
    q = quote(0.6, partner_share=0.25, months_in_storage=6, depot=SANGRUR, site=PATIALA, margin_pct=10)
    d = q.as_dict()
    assert d["farm_gate_per_t"] == 600
    assert d["collection_per_t"] == pytest.approx(0.75 * OWN_COLLECTION_PER_T_INR + 0.25 * PARTNER_COLLECTION_PER_T_INR)
    assert d["storage_per_t"] == 6 * STORAGE_PER_T_MONTH_INR
    assert d["cost_per_t"] == pytest.approx(d["farm_gate_per_t"] + d["collection_per_t"] + d["storage_per_t"] + d["haul_per_t"], abs=0.02)
    assert d["price_per_t"] == pytest.approx(d["cost_per_t"] * 1.10, abs=0.05)
    assert d["in_season_benchmark_per_t"] == IN_SEASON_DELIVERED_PER_T_INR


def test_quote_rejects_bad_inputs():
    with pytest.raises(ValueError):
        quote(0.6, partner_share=1.5, months_in_storage=1, depot=SANGRUR, site=PATIALA)
    with pytest.raises(ValueError):
        quote(0.6, partner_share=0, months_in_storage=-1, depot=SANGRUR, site=PATIALA)


# ---- procurement

def test_posted_price_is_base_when_supply_is_plentiful_and_bounded_when_scarce():
    assert posted_price(0) == FARM_GATE_BASE_PER_KG
    assert posted_price(-50) == FARM_GATE_BASE_PER_KG
    assert FARM_GATE_MIN_PER_KG <= posted_price(400) <= FARM_GATE_MAX_PER_KG
    assert posted_price(400) > FARM_GATE_BASE_PER_KG
    assert posted_price(1e9) == FARM_GATE_MAX_PER_KG


def test_plenty_of_supply_means_base_price_and_no_shortfall():
    plan = plan_procurement([supply(weekly=(5000, 5000))], [depot()],
                            SalesBook(committed_t=600, committed_price_per_t=2600, forecast_t=0, forecast_price_per_t=0))
    assert plan.status == "optimal" and plan.shortfall_t == 0
    assert plan.sell_committed_t == pytest.approx(600)
    assert all(p == FARM_GATE_BASE_PER_KG for p in plan.posted_price_per_kg.values())


def test_scarce_supply_raises_the_posted_price():
    """Committed orders exceed what farmers in the district are expected to
    book, so another tonne from there is valuable: the shadow price is
    positive and the posted price rises above base."""
    plan = plan_procurement([supply(weekly=(200, 200))], [depot()],
                            SalesBook(committed_t=1000, committed_price_per_t=2600, forecast_t=0, forecast_price_per_t=0))
    assert plan.shortfall_t == pytest.approx(600)
    assert all(p > FARM_GATE_BASE_PER_KG for p in plan.posted_price_per_kg.values())
    assert all(s > 0 for s in plan.shadow_price_per_t.values())


def test_districts_outside_every_depot_radius_are_not_bought_from():
    far = supply("Bathinda", BATHINDA, weekly=(5000,))
    plan = plan_procurement([far], [depot(radius=40)],
                            SalesBook(committed_t=100, committed_price_per_t=2600, forecast_t=0, forecast_price_per_t=0))
    assert plan.buy == {} and plan.shortfall_t == pytest.approx(100)


def test_own_crews_are_used_before_partners_and_capacity_holds():
    plan = plan_procurement([supply(weekly=(700,))], [depot(own=500, partner=300)],
                            SalesBook(committed_t=700, committed_price_per_t=2600, forecast_t=0, forecast_price_per_t=0))
    assert plan.own_t[("dep_sangrur", 0)] == pytest.approx(500)
    assert plan.partner_t[("dep_sangrur", 0)] == pytest.approx(200)
    assert plan.district_depot_share("Sangrur") == {"dep_sangrur": pytest.approx(700)}


def test_forecast_demand_is_only_bought_when_it_pays():
    cheap = plan_procurement([supply(weekly=(1000,))], [depot()],
                             SalesBook(committed_t=0, committed_price_per_t=0, forecast_t=500, forecast_price_per_t=900))
    assert cheap.sell_forecast_t == 0
    good = plan_procurement([supply(weekly=(1000,))], [depot()],
                            SalesBook(committed_t=0, committed_price_per_t=0, forecast_t=500, forecast_price_per_t=3000))
    assert good.sell_forecast_t == pytest.approx(500)


# ---- deliveries

def test_inventory_carries_over_and_orders_are_met():
    depots = [DepotStock("d1", *SANGRUR, capacity_t=5000, opening_t=0, inbound_t_by_month=(1200, 0, 0))]
    orders = [OrderLine("o1", "c1", *PATIALA, tonnes_by_month=(400, 400, 400))]
    plan = plan_deliveries(depots, orders, months=3)
    assert plan.status == "optimal" and plan.total_shortfall_t == 0
    assert [plan.stock[("d1", m)] for m in range(3)] == [800, 400, 0]
    assert plan.haul_cost_inr > 0 and plan.storage_cost_inr == pytest.approx(1200 * STORAGE_PER_T_MONTH_INR)


def test_shortfall_is_reported_not_hidden():
    depots = [DepotStock("d1", *SANGRUR, capacity_t=5000, opening_t=0, inbound_t_by_month=(500,))]
    orders = [OrderLine("o1", "c1", *PATIALA, tonnes_by_month=(300, 300))]
    plan = plan_deliveries(depots, orders, months=2)
    assert plan.total_shortfall_t == pytest.approx(100)
    assert plan.shortfall == {("o1", 1): pytest.approx(100)}


def test_nearest_depot_ships_first():
    depots = [DepotStock("near", *PATIALA, 5000, 1000, (0,)), DepotStock("far", *BATHINDA, 5000, 1000, (0,))]
    orders = [OrderLine("o1", "c1", PATIALA[0] + 0.05, PATIALA[1], tonnes_by_month=(500,))]
    plan = plan_deliveries(depots, orders, months=1)
    assert plan.shipments == {("near", "o1", 0): pytest.approx(500)}
