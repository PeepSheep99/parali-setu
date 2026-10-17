"""Break-even from both sides: the arithmetic, and that it is shown even when
it does not favour us."""
import pytest

import economics
from test_api_flows import api, client  # noqa: F401


QUOTE = {"price_per_t": 2388, "cost_per_t": 2171, "margin_per_t": 217}


def test_buying_at_harvest_counts_loss_storage_and_cash():
    case = economics.company_case(QUOTE, 300, 12, 6.0)
    low = case["buy_at_harvest"]["low_loss"]
    # 15%/yr for 6 months = 7.5% lost, so 1/0.925 t bought per usable tonne
    assert low["loss_pct"] == 7.5 and low["buy_per_usable_t"] == pytest.approx(1 / 0.925, abs=1e-3)
    assert low["price_per_t"] == round(1690 / 0.925)
    assert low["storage_per_t"] == round(60 * 6 / 0.925)
    assert low["interest_per_t"] == round(1690 / 0.925 * 0.10 * 0.5)
    assert low["per_usable_t"] == round(low["price_per_t"] + low["storage_per_t"] + low["interest_per_t"], -0) or \
        abs(low["per_usable_t"] - (low["price_per_t"] + low["storage_per_t"] + low["interest_per_t"])) <= 1
    assert case["buy_at_harvest"]["high_loss"]["per_usable_t"] > low["per_usable_t"]
    assert case["ours"]["upfront_inr"] == 0 and case["buy_at_harvest"]["upfront_inr"] > 3600 * 1690


def test_a_negative_saving_is_reported_not_hidden():
    dear = {**QUOTE, "price_per_t": 5000}
    case = economics.company_case(dear, 100, 3, 1.0)
    assert case["saving_per_t"]["low"] < 0 and case["saving_contract_inr"]["high"] < 0


def test_farmer_three_ways():
    f = economics.farmer_case(10, 0.76)
    assert f["straw_t"] == 17.5 and f["parali_setu"]["farmer_gets"] == round(17500 * 0.76)
    assert f["hire_baler"]["farmer_pays"] == (25000, 40000)
    assert f["burn"]["fine_if_caught"] == 30000
    assert f["better_than_baler"] == (13300 + 25000, 13300 + 40000)
    assert economics.burning_fine(1.5) == 5000 and economics.burning_fine(3) == 10000


def test_quote_carries_the_comparison_and_farmer_endpoint(api):
    body = client.post("/customers/cust_cbg/quote", json={"tonnes_per_month": 300, "months": 12,
                                                          "start_month": "2026-11-01"}).json()
    vs = body["vs_buying_at_harvest"]
    assert vs["ours"]["per_t"] == body["quote"]["price_per_t"] and vs["total_t"] == 3600
    farmer = client.get("/economics/farmer", params={"acres": 8, "district": "Bathinda"}).json()
    assert farmer["district"] == "Bathinda" and farmer["parali_setu"]["farmer_pays"] == 0
