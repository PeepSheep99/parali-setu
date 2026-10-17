"""BigQuery SQL for the supply-timing forecast.

The series is weekly fire pixels per district, zero-filled across the whole
year so every district has a regular series from 2001. Two forecasters run
over the same series and the same cut-off, so their backtest scores compare
like with like:

- TimesFM through `AI.FORECAST` (Google's pretrained time-series foundation
  model; nothing to train), and
- ARIMA_PLUS, trained per district with `CREATE MODEL`.
"""
from __future__ import annotations

import re

_IDENT = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){1,2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"not a dataset.table name: {name!r}")
    return f"`{name}`"


def _date(value: str) -> str:
    if not _DATE.match(value):
        raise ValueError(f"not an ISO date: {value!r}")
    return value


def weekly_series_sql(daily_table: str, weekly_table: str, first_week: str, last_week: str) -> str:
    """Weekly (Monday) fire pixels per district, with explicit zero weeks."""
    return f"""
CREATE OR REPLACE TABLE {_ident(weekly_table)} AS
WITH weeks AS (
  SELECT week FROM UNNEST(GENERATE_DATE_ARRAY(DATE '{_date(first_week)}', DATE '{_date(last_week)}', INTERVAL 1 WEEK)) AS week
),
districts AS (SELECT DISTINCT state, district FROM {_ident(daily_table)}),
counts AS (
  SELECT DATE_TRUNC(date, WEEK(MONDAY)) AS week, state, district, SUM(fire_pixels) AS fire_pixels
  FROM {_ident(daily_table)} GROUP BY 1, 2, 3
)
SELECT w.week, d.state, d.district, IFNULL(c.fire_pixels, 0) AS fire_pixels
FROM weeks w CROSS JOIN districts d
LEFT JOIN counts c USING (week, state, district)
""".strip()


def timesfm_forecast_sql(weekly_table: str, context_end: str, horizon_weeks: int) -> str:
    if not 1 <= horizon_weeks <= 104:
        raise ValueError("horizon_weeks must be 1-104")
    return f"""
SELECT district, forecast_timestamp, forecast_value, prediction_interval_lower_bound, prediction_interval_upper_bound
FROM AI.FORECAST(
  (SELECT TIMESTAMP(week) AS week, district, fire_pixels FROM {_ident(weekly_table)} WHERE week <= DATE '{_date(context_end)}'),
  data_col => 'fire_pixels',
  timestamp_col => 'week',
  id_cols => ['district'],
  horizon => {horizon_weeks},
  confidence_level => 0.8
)
""".strip()


def arima_train_sql(weekly_table: str, model: str, context_end: str) -> str:
    return f"""
CREATE OR REPLACE MODEL {_ident(model)}
OPTIONS (
  model_type = 'ARIMA_PLUS',
  time_series_timestamp_col = 'week',
  time_series_data_col = 'fire_pixels',
  time_series_id_col = 'district',
  data_frequency = 'WEEKLY',
  auto_arima = TRUE
) AS
SELECT TIMESTAMP(week) AS week, district, fire_pixels
FROM {_ident(weekly_table)} WHERE week <= DATE '{_date(context_end)}'
""".strip()


def arima_forecast_sql(model: str, horizon_weeks: int) -> str:
    if not 1 <= horizon_weeks <= 104:
        raise ValueError("horizon_weeks must be 1-104")
    return f"""
SELECT district, forecast_timestamp, forecast_value, prediction_interval_lower_bound, prediction_interval_upper_bound
FROM ML.FORECAST(MODEL {_ident(model)}, STRUCT({horizon_weeks} AS horizon, 0.8 AS confidence_level))
""".strip()


def actuals_sql(weekly_table: str, start: str, end: str) -> str:
    return f"""
SELECT district, week, fire_pixels FROM {_ident(weekly_table)}
WHERE week > DATE '{_date(start)}' AND week <= DATE '{_date(end)}'
""".strip()
