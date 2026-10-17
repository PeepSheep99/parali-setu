"""Runs the supply-timing forecast in BigQuery and saves the results.

    python -m forecast.pipeline backtest --season 2024    # held-out score
    python -m forecast.pipeline live                      # this season, from today's data
    python -m forecast.pipeline weekly                    # refresh this season's fires, then live (Cloud Run job)

Backtest: both models see weekly fire pixels per district up to 30 June of
the season's year and forecast the next 26 weeks; the paddy weeks (Sep-Dec)
are scored against what happened, next to a seasonal-naive baseline (the
same weeks a year earlier). Live: the same forecast from the latest week we
have, for the rest of the current season.

Results go to Firestore `forecasts/` for the ops console and the landing
page; nothing here is computed at request time.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from forecast import metrics, queries

DATASET = "parali_forecast"
DAILY = f"{DATASET}.fires_daily"
WEEKLY = f"{DATASET}.fires_weekly"
ARIMA = f"{DATASET}.fires_arima"
FIRST_WEEK = "2002-01-07"     # MODIS Aqua joined in 2002; 2001 is incomplete
LOCATION = "asia-southeast1"
SEASON_MONTHS = (9, 10, 11, 12)


def _client():
    from google.cloud import bigquery

    import firestore_store as store
    return bigquery.Client(project=store.PROJECT_ID, location=LOCATION)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build_weekly(client, last_week: date) -> None:
    client.query(queries.weekly_series_sql(DAILY, WEEKLY, FIRST_WEEK, last_week.isoformat())).result()


def _rows(client, sql: str) -> list[dict]:
    return [dict(r) for r in client.query(sql).result()]


def _as_date(t: date | datetime) -> date:
    return t.date() if isinstance(t, datetime) else t


def _series(rows: list[dict], time_key: str, value_key: str) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}
    for r in rows:
        out.setdefault(r["district"], {})[_as_date(r[time_key])] = float(r[value_key])
    return out


def season_weeks(year: int) -> list[date]:
    """Mondays from the first one on or after 1 Sep to the last one in December."""
    first = date(year, 9, 1)
    week = first + timedelta(days=(7 - first.weekday()) % 7)
    out = []
    while week.year == year and week.month in SEASON_MONTHS:
        out.append(week)
        week += timedelta(weeks=1)
    return out


def backtest(season: int) -> dict:
    client = _client()
    cutoff = date(season, 6, 30)
    horizon = 27
    timesfm = _series(_rows(client, queries.timesfm_forecast_sql(WEEKLY, cutoff.isoformat(), horizon)),
                      "forecast_timestamp", "forecast_value")
    client.query(queries.arima_train_sql(WEEKLY, ARIMA, cutoff.isoformat())).result()
    arima = _series(_rows(client, queries.arima_forecast_sql(ARIMA, horizon)), "forecast_timestamp", "forecast_value")
    history = _series(_rows(client, queries.actuals_sql(WEEKLY, date(season - 1, 6, 30).isoformat(),
                                                         date(season, 12, 31).isoformat())), "week", "fire_pixels")

    weeks = season_weeks(season)
    results: dict[str, dict] = {}
    for name, forecast in (("timesfm", timesfm), ("arima_plus", arima), ("last_year", None)):
        scores, weights = [], []
        for district, actual_by_week in history.items():
            actual = [actual_by_week.get(w, 0.0) for w in weeks]
            if forecast is None:
                predicted = [actual_by_week.get(w - timedelta(weeks=52), 0.0) for w in weeks]
            else:
                predicted = [forecast.get(district, {}).get(w, 0.0) for w in weeks]
            scores.append(metrics.score(actual, predicted))
            weights.append(sum(actual))
        results[name] = metrics.pooled(scores, weights)
    return {
        "season": season, "cutoff": cutoff.isoformat(), "season_weeks": [w.isoformat() for w in weeks],
        "districts": len(history), "actual_fire_pixels": round(sum(sum(v.get(w, 0.0) for w in weeks) for v in history.values())),
        "scores": results,
    }


def live(today: date) -> dict:
    client = _client()
    last = _monday(today) - timedelta(weeks=1)
    build_weekly(client, last)
    remaining = [w for w in season_weeks(today.year) if w > last]
    horizon = max(1, len(remaining))
    rows = _rows(client, queries.timesfm_forecast_sql(WEEKLY, last.isoformat(), horizon))
    by_district = {}
    for r in rows:
        by_district.setdefault(r["district"], []).append({
            "week": _as_date(r["forecast_timestamp"]).isoformat(),
            "fire_pixels": round(max(0.0, float(r["forecast_value"])), 1),
            "low": round(max(0.0, float(r["prediction_interval_lower_bound"])), 1),
            "high": round(max(0.0, float(r["prediction_interval_upper_bound"])), 1),
        })
    for weeks in by_district.values():
        weeks.sort(key=lambda w: w["week"])
    season_start = season_weeks(today.year)[0] - timedelta(days=1)
    observed = _series(_rows(client, queries.actuals_sql(WEEKLY, season_start.isoformat(), last.isoformat())),
                       "week", "fire_pixels")
    return {"model": "TimesFM (BigQuery AI.FORECAST)", "context_end": last.isoformat(),
            "horizon_weeks": horizon, "districts": by_district,
            "observed_to_date": {d: round(sum(v.values()), 1) for d, v in observed.items()}}


def refresh_current_season(today: date) -> int:
    """Re-counts this season's fires in Earth Engine and replaces the
    season's rows in BigQuery, so the weekly forecast starts from today's
    data rather than whatever was loaded last."""
    from google.cloud import bigquery

    import firestore_store as store
    from forecast import firms_history

    rows = firms_history.season_rows(today.year, store.PROJECT_ID)
    client = _client()
    client.query(f"DELETE FROM `{DAILY}` WHERE EXTRACT(YEAR FROM date) = {int(today.year)}").result()
    if rows:
        schema = [bigquery.SchemaField("date", "DATE"), bigquery.SchemaField("state", "STRING"),
                  bigquery.SchemaField("district", "STRING"), bigquery.SchemaField("fire_pixels", "INT64")]
        client.load_table_from_json(rows, f"{store.PROJECT_ID}.{DAILY}",
                                    job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND")).result()
    return len(rows)


def save(doc_id: str, payload: dict, out_dir: Path) -> None:
    import firestore_store as store

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{doc_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    store.get_firestore_client().collection("forecasts").document(doc_id).set(payload)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest")
    b.add_argument("--season", type=int, required=True)
    sub.add_parser("live")
    sub.add_parser("weekly", help="refresh this season's fires in BigQuery from Earth Engine, then forecast")
    parser.add_argument("--out", type=Path, default=Path("forecast/data/results"))
    args = parser.parse_args(argv)
    if args.cmd == "backtest":
        result = backtest(args.season)
        save(f"supply_backtest_{args.season}", result, args.out)
    else:
        import pickups
        if args.cmd == "weekly":
            print(f"refreshed {refresh_current_season(pickups.now_ist().date())} district-days for this season")
        result = live(pickups.now_ist().date())
        save(f"supply_live_{pickups.now_ist().year}", result, args.out)
    print(json.dumps(result if args.cmd == "backtest" else {k: v for k, v in result.items() if k != "districts"}, indent=2))


if __name__ == "__main__":
    main()
