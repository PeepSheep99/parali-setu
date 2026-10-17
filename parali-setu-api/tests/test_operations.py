"""The planners on (fake) live data: posted prices, booking, deliveries and
quotes."""
from datetime import date

import pytest

import firestore_store as store
import operations
from costs import FARM_GATE_MAX_PER_KG, FARM_GATE_MIN_PER_KG
from geo import DISTRICT_COORDS

TODAY = date(2026, 10, 17)


def test_district_straw_comes_from_the_crop_statistics():
    straw = operations.district_straw_t()
    assert set(straw) == set(DISTRICT_COORDS)
    assert straw["Sangrur"]["year"] == 2019 and straw["Sangrur"]["straw_t"] == pytest.approx(straw["Sangrur"]["rice_t"] * 1.5)


def test_season_timing_without_a_forecast_is_even_and_says_half_remains():
    weeks = [date(2026, 10, 12), date(2026, 10, 19)]
    assert operations.season_timing(None, "Sangrur", weeks) == ([0.5, 0.5], 0.5)


def test_procurement_posts_a_bounded_price_with_a_reason_for_every_district(world):
    prices = store.get_posted_prices_for_day(world, TODAY.isoformat())
    assert {p["district"] for p in prices} == set(DISTRICT_COORDS)
    for p in prices:
        assert FARM_GATE_MIN_PER_KG <= p["price_per_kg"] <= FARM_GATE_MAX_PER_KG
        assert p["reason"] and p["reason_code"] in ("base", "scarce")
        assert (p["reason_code"] == "scarce") == (p["shadow_price_per_t"] > 0)
    plan = store.get_plan(world, "procurement_current")
    assert plan["shortfall_t"] == 0 and plan["committed_t"] > 0
    assert plan["assumptions"]["forecast"].startswith("TimesFM")


def test_booking_takes_todays_price_and_the_planned_depot(world):
    lat, lon = DISTRICT_COORDS["Sangrur"]
    listing = store.save_listing(world, "f1", {"acres": 5, "quantity_kg": 8750.0, "crop_type": "rice_stubble",
                                                "district": "Sangrur", "lat": lat, "lon": lon}, "Hindi")
    booking, price = operations.book_listing(world, listing, TODAY)
    assert booking["status"] == "offered" and booking["price_per_kg"] == price["price_per_kg"]
    shares = store.get_plan(world, "procurement_current")["district_depot_share"]["Sangrur"]
    assert booking["depot_id"] == max(shares, key=shares.get)


def test_a_farm_no_depot_reaches_is_not_booked(world):
    listing = store.save_listing(world, "f1", {"acres": 5, "quantity_kg": 8750.0, "crop_type": "rice_stubble",
                                                "lat": 28.61, "lon": 77.21}, "Hindi")   # Delhi
    booking, _ = operations.book_listing(world, listing, TODAY)
    assert booking is None


def test_deliveries_meet_orders_from_planned_intake(world):
    plan = operations.run_deliveries(world, TODAY)
    assert plan["status"] == "optimal" and plan["shortfall_t"] == 0
    shipped = sum(d["tonnes"] for d in store.get_deliveries(world))
    ordered = sum(t for o in store.get_orders(world) for m, t in o["tonnes_by_month"].items()
                  if m < operations.add_months(date(2026, 10, 1), operations.DELIVERY_MONTHS).isoformat())
    assert shipped == pytest.approx(ordered, rel=1e-6)


def test_an_order_beyond_what_we_can_collect_shows_a_shortfall(world):
    store.save_order(world, {"customer_id": "cust_power", "tonnes_by_month": {"2026-11-01": 500_000.0},
                             "site": {"lat": 30.27, "lon": 74.9}, "quote": {"price_per_t": 2400}})
    operations.run_procurement(world, TODAY)
    plan = operations.run_deliveries(world, TODAY)
    assert plan["shortfall_t"] > 0
    assert any(s["month"] == "2026-11-01" for s in plan["shortfall"])


def test_quote_uses_the_nearest_depot_and_adds_up(world):
    site = DISTRICT_COORDS["Bathinda"]
    q = operations.quote_order(world, site, date(2026, 11, 1), 12, today=TODAY)
    assert q["depot_id"] == "dep_bathinda"
    assert q["price_per_t"] == pytest.approx(q["cost_per_t"] + q["margin_per_t"], abs=0.02)
    assert q["in_season_benchmark_per_t"] == 1690.0


def test_storage_months_count_from_the_november_peak():
    assert operations.months_in_storage(date(2026, 12, 1), 1) == pytest.approx(1.18, abs=0.01)
    assert operations.months_in_storage(date(2027, 5, 1), 1) == pytest.approx(6.15, abs=0.01)
    assert operations.months_in_storage(date(2026, 10, 1), 1) == pytest.approx(11.18, abs=0.01), "October draws on last season's stock"
