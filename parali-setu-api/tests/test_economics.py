"""What a farmer gains, three ways."""
import economics
from test_api_flows import api, client  # noqa: F401


def test_farmer_three_ways():
    f = economics.farmer_case(10, 0.76)
    assert f["straw_t"] == 17.5 and f["parali_setu"]["farmer_gets"] == round(17500 * 0.76)
    assert f["hire_baler"]["farmer_pays"] == (25000, 40000)
    assert f["burn"]["fine_if_caught"] == 30000
    assert f["better_than_baler"] == (13300 + 25000, 13300 + 40000)
    assert economics.burning_fine(1.5) == 5000 and economics.burning_fine(3) == 10000


def test_farmer_endpoint_uses_todays_posted_price(api):
    farmer = client.get("/economics/farmer", params={"acres": 8, "district": "Bathinda"}).json()
    assert farmer["district"] == "Bathinda" and farmer["parali_setu"]["farmer_pays"] == 0
    assert farmer["price_per_kg"] > 0
