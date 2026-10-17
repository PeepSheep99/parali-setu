"""Shared Gemini client + retry wrapper for Parali Setu.

Deliberately mirrors aidatlas-api/main.py's proven get_gemini_client() /
call_gemini() pattern verbatim -- same project, same already-solved
gotchas (Developer API's 20/day cap, gemini-2.5-flash deprecation,
region-specific endpoints 404ing), no reason to rediscover any of them.

Every function here does language in, language or JSON-shaped-text out.
None of them touch a price or a quantity decision -- that's solver.py's
job, always (PRD docs/PARALI_SETU_PRD.md, Section 9 / 13).
"""
from __future__ import annotations

import os
import time

from google import genai
from google.genai import errors as genai_errors

# gemini-3.5-flash: about 1 s per agent step in tests on 17 Oct 2026, while
# gemini-3.8-flash on the same endpoint was returning 429s and 504s.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "ai-builder-cup-aidatlas")
VERTEX_LOCATION = os.environ.get("AGENT_PLATFORM_LOCATION", "global")

# After a 429, skip Gemini for this long instead of forever. The original
# permanent flag meant one quota blip disabled Gemini until the Cloud Run
# instance happened to recycle.
QUOTA_COOLDOWN_SECONDS = 60
_quota_cooldown_until = 0.0


def quota_cooling_down() -> bool:
    return time.monotonic() < _quota_cooldown_until


def reset_quota_cooldown() -> None:
    global _quota_cooldown_until
    _quota_cooldown_until = 0.0


# A model call that has not answered in 20 s is abandoned (the agent then tries
# its fallback) instead of leaving a farmer waiting a minute or more; the SDK's own
# retries are off because callers decide how to retry.
REQUEST_HTTP_OPTIONS = genai.types.HttpOptions(timeout=20_000, retry_options=genai.types.HttpRetryOptions(attempts=1))


def get_gemini_client() -> genai.Client:
    return genai.Client(vertexai=True, project=PROJECT_ID, location=VERTEX_LOCATION, http_options=REQUEST_HTTP_OPTIONS)


def call_gemini(client: genai.Client, contents, json_mode: bool = False) -> str | None:
    """Three retries on transient server errors, then gives up and returns
    None -- callers must handle None explicitly (show a plain error, never
    fabricate a result). PRD Section 13: 'if a Gemini call fails, show a
    plain error -- never let the model guess a price or quantity.'

    `contents` is whatever the SDK accepts: a plain string for the
    text-only jobs (extraction, negotiation parsing, narration), or a
    list of Parts (text + image) for the multimodal quality read -- the
    retry/quota logic doesn't care which.

    Once a 429 is seen, later calls skip straight to None for
    QUOTA_COOLDOWN_SECONDS with zero wasted retries, rather than
    re-discovering the same quota exhaustion three times per request.
    After the cooldown Gemini is tried again.
    """
    global _quota_cooldown_until
    if quota_cooling_down():
        return None

    config = {"thinking_config": {"thinking_budget": 0}}   # short extraction tasks: no hidden reasoning time
    if json_mode:
        config["response_mime_type"] = "application/json"

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=config
            )
            return response.text
        except genai_errors.ServerError:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            continue
        except genai_errors.ClientError as exc:
            if exc.code == 429:
                _quota_cooldown_until = time.monotonic() + QUOTA_COOLDOWN_SECONDS
                return None
            raise

    return None
