import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecast import demand_segments, metrics, queries  # noqa: E402


def test_weekly_series_sql_zero_fills_and_names_tables():
    sql = queries.weekly_series_sql("parali_forecast.fires_daily", "parali_forecast.fires_weekly", "2001-01-01", "2025-12-29")
    assert "GENERATE_DATE_ARRAY(DATE '2001-01-01', DATE '2025-12-29', INTERVAL 1 WEEK)" in sql
    assert "IFNULL(c.fire_pixels, 0)" in sql
    assert "`parali_forecast.fires_weekly`" in sql


def test_timesfm_sql_uses_ai_forecast_per_district():
    sql = queries.timesfm_forecast_sql("parali_forecast.fires_weekly", "2024-06-30", 26)
    assert "AI.FORECAST(" in sql and "id_cols => ['district']" in sql and "horizon => 26" in sql
    assert "week <= DATE '2024-06-30'" in sql


def test_arima_sql_trains_per_district_up_to_cutoff():
    sql = queries.arima_train_sql("parali_forecast.fires_weekly", "parali_forecast.fires_arima", "2024-06-30")
    assert "'ARIMA_PLUS'" in sql and "time_series_id_col = 'district'" in sql
    assert "week <= DATE '2024-06-30'" in sql
    assert "horizon" in queries.arima_forecast_sql("parali_forecast.fires_arima", 26)


@pytest.mark.parametrize("bad", ["fires; DROP TABLE x", "a", "a.b.c.d", "a.b`"])
def test_sql_builders_reject_unsafe_names(bad):
    with pytest.raises(ValueError):
        queries.weekly_series_sql(bad, "d.t", "2001-01-01", "2001-02-01")


def test_sql_builders_reject_bad_dates_and_horizons():
    with pytest.raises(ValueError):
        queries.timesfm_forecast_sql("d.t", "2024-6-30", 26)
    with pytest.raises(ValueError):
        queries.timesfm_forecast_sql("d.t", "2024-06-30", 0)


def test_wape_and_timing():
    actual = [0, 10, 30, 10, 0]
    assert metrics.wape(actual, actual) == 0
    assert metrics.wape(actual, [0, 0, 0, 0, 0]) == 1
    # Same shape at half the volume: volume is wrong, timing is perfect.
    half = [x / 2 for x in actual]
    assert metrics.wape(actual, half) == pytest.approx(0.5)
    assert metrics.timing_wape(actual, half) == pytest.approx(0)
    assert metrics.peak_shift_weeks(actual, [0, 0, 10, 30, 0]) == 1
    assert metrics.wape([0, 0], [1, 1]) is None
    assert metrics.peak_shift_weeks([0, 0], [1, 2]) is None


def test_pooled_weights_by_volume():
    big = {"wape": 0.2, "timing_wape": 0.1, "peak_shift_weeks": 0}
    small = {"wape": 1.0, "timing_wape": 1.0, "peak_shift_weeks": 3}
    out = metrics.pooled([big, small], [900, 100])
    assert out["wape"] == pytest.approx(0.28)
    assert out["mean_abs_peak_shift_weeks"] == pytest.approx(0.3)


def test_demand_segments_are_sourced_and_match_state_totals():
    for s in demand_segments.SEGMENTS:
        assert s.sources and all(u.startswith("https://") for u in s.sources)
        assert 0 < s.annual_t_low <= s.annual_t_high
    low, high = demand_segments.segment_totals()
    # The segment sum should sit near the state's own 2024 figure and 2025 target.
    assert 0.8 * demand_segments.EX_SITU_TOTAL_T["2024"] <= low
    assert high <= 1.15 * demand_segments.EX_SITU_TOTAL_T["2025 target"]


def test_monthly_demand_spreads_evenly_and_scales_by_share():
    rows = demand_segments.monthly_demand(2026, share=0.02)
    assert len(rows) == 12 * len(demand_segments.SEGMENTS)
    power = [r for r in rows if r["segment"] == "biomass_power"]
    assert sum(r["tonnes_low"] for r in power) == pytest.approx(11.7e5 * 0.02, rel=1e-3)
    with pytest.raises(ValueError):
        demand_segments.monthly_demand(2026, share=0)


def test_season_weeks_start_on_the_first_monday_in_september():
    from datetime import date
    from forecast.pipeline import season_weeks
    weeks = season_weeks(2024)          # 1 Sep 2024 was a Sunday
    assert weeks[0] == date(2024, 9, 2) and weeks[-1] == date(2024, 12, 30)
    assert all(w.weekday() == 0 for w in weeks) and len(weeks) == 18
    assert season_weeks(2025)[0] == date(2025, 9, 1)   # a Monday
