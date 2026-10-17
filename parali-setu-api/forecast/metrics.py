"""Backtest scores for a season-timing forecast.

Weekly fire counts are mostly zeros outside the season, so plain MAPE is
meaningless (division by zero). What matters for planning crews is *when* the
season peaks and *how the season is shaped*, so the scores are:

- WAPE: total absolute error over total actual, over the season weeks;
- timing WAPE: the same on each series normalised to its own season total
  (the shape, ignoring how many fires there were);
- peak shift: forecast peak week minus actual peak week, in weeks.

A seasonal-naive baseline (last year's same weeks) is scored the same way;
a model is only worth using if it beats it.
"""
from __future__ import annotations


def wape(actual: list[float], forecast: list[float]) -> float | None:
    if len(actual) != len(forecast):
        raise ValueError("series lengths differ")
    total = sum(abs(a) for a in actual)
    if total == 0:
        return None
    return sum(abs(a - f) for a, f in zip(actual, forecast)) / total


def _shape(series: list[float]) -> list[float]:
    clipped = [max(0.0, x) for x in series]
    total = sum(clipped)
    return [x / total for x in clipped] if total else clipped


def timing_wape(actual: list[float], forecast: list[float]) -> float | None:
    return wape(_shape(actual), _shape(forecast))


def peak_shift_weeks(actual: list[float], forecast: list[float]) -> int | None:
    if not actual or max(actual) <= 0 or max(forecast) <= 0:
        return None
    return forecast.index(max(forecast)) - actual.index(max(actual))


def score(actual: list[float], forecast: list[float]) -> dict:
    return {
        "wape": wape(actual, forecast),
        "timing_wape": timing_wape(actual, forecast),
        "peak_shift_weeks": peak_shift_weeks(actual, forecast),
    }


def pooled(scores: list[dict], weights: list[float]) -> dict:
    """Weight each district's score by its actual season volume, so a
    district with 3 fires doesn't count as much as one with 4,000."""
    out = {}
    for key in ("wape", "timing_wape"):
        pairs = [(s[key], w) for s, w in zip(scores, weights) if s[key] is not None and w > 0]
        total_w = sum(w for _, w in pairs)
        out[key] = sum(v * w for v, w in pairs) / total_w if total_w else None
    shifts = [(abs(s["peak_shift_weeks"]), w) for s, w in zip(scores, weights)
              if s["peak_shift_weeks"] is not None and w > 0]
    total_w = sum(w for _, w in shifts)
    out["mean_abs_peak_shift_weeks"] = sum(v * w for v, w in shifts) / total_w if total_w else None
    return out
