"""Farmer trust score from no-burn proofs: a photo read by Gemini and an
independent satellite check, combined by a fixed, bounded rule.

The score is shown to ops (who decides whether to dispute a claim) and is
never used to set a price.
"""
from __future__ import annotations

TRUST_SCORE_DEFAULT = 0.5

PHOTO_DELTA = {"unburned": 0.10, "partially_burned": -0.05, "burned": -0.20}
SATELLITE_DELTA = {"no_fire_detected": 0.05, "fire_detected": -0.15, "no_data": 0.0}


def score_no_burn_submission(previous_score: float | None, field_condition: str | None,
                             satellite_corroboration: str) -> dict:
    """The photo read and the satellite check are two independent, capped
    pieces of evidence, summed; neither overrides the other.

    `field_condition` is Gemini's perception of the photo: "unburned",
    "partially_burned", "burned", "inconclusive" or None.
    `satellite_corroboration` is "no_fire_detected", "fire_detected" or
    "no_data", from the NASA FIRMS batch, never invented here.

    A photo claiming "unburned" while satellites saw fire is flagged
    `disputed` for a person to review rather than resolved by formula."""
    previous = TRUST_SCORE_DEFAULT if previous_score is None else previous_score
    delta = PHOTO_DELTA.get(field_condition, 0.0) + SATELLITE_DELTA.get(satellite_corroboration, 0.0)
    new_score = min(1.0, max(0.0, previous + delta))
    disputed = field_condition == "unburned" and satellite_corroboration == "fire_detected"
    return {"new_score": round(new_score, 3), "disputed": disputed}
