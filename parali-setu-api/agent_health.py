"""How the farmer agent is doing: speed, fallbacks and what its guardrails
caught, read from the guardrail report every turn already stores
(agent.respond), plus the last measured benchmark (bench/bench_agent.py).

Pure functions over conversation records, so the ops console shows numbers
counted here, not estimated.
"""
from __future__ import annotations

import json
from pathlib import Path

BENCH_FILE = Path(__file__).resolve().parent / "bench" / "results" / "agent.json"


def _pct(values: list[float], q: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo))


def summarise(conversations: list[dict]) -> dict:
    """Counts over the model's turns in these conversations. Turns recorded
    before timing existed count for guardrails but not for speed."""
    turns = [t for c in conversations for t in c.get("turns", []) if t.get("role") == "model" and t.get("guardrails")]
    reports = [t["guardrails"] for t in turns]
    calls = [m for r in reports for m in r.get("model_calls", [])]
    timed = [r for r in reports if r.get("model_calls")]
    n = len(reports)

    def share(pred) -> float | None:
        return round(100 * sum(1 for r in reports if pred(r)) / n, 1) if n else None

    return {
        "conversations": len(conversations),
        "bookings": sum(1 for c in conversations if c.get("booking_id")),
        "turns": n,
        "model_ms_per_turn": {"p50": _pct([sum(m["ms"] for m in r["model_calls"]) for r in timed], .5),
                              "p95": _pct([sum(m["ms"] for m in r["model_calls"]) for r in timed], .95),
                              "turns_timed": len(timed)},
        "model_call_ms": {"p50": _pct([m["ms"] for m in calls], .5), "p95": _pct([m["ms"] for m in calls], .95)},
        "fallback_model_pct": round(100 * sum(m["model"] == "fallback" for m in calls) / len(calls), 1) if calls else None,
        "rewritten_pct": share(lambda r: r.get("regenerated")),
        "template_pct": share(lambda r: r.get("fallback")),
        "caught": {"unverified_numbers": sum(1 for r in reports if r.get("blocked_numbers")),
                   "forbidden_claims": sum(1 for r in reports if r.get("blocked_claims")),
                   "wrong_language": sum(1 for r in reports if r.get("wrong_language"))},
    }


def benchmark() -> dict | None:
    """The last benchmark run's summary, or None if it was never run here."""
    try:
        saved = json.loads(BENCH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    s = saved.get("summary") or {}
    keep = ("bookings_completed", "median_turns_to_booking", "median_s_to_booking", "turn_ms", "model_call_ms",
            "fallback_model_share_pct", "first_drafts_rewritten_pct", "drafts_with_ungrounded_numbers",
            "replies_leaking_a_number", "template_replies_pct", "field_accuracy_pct", "reply_language_ok_pct",
            "adversarial_passed", "adversarial", "language_detection", "voice", "turns")
    return {"ran_at": saved.get("ran_at"), **{k: s[k] for k in keep if k in s}}
