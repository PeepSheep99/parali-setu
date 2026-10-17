"""A per-visitor and a whole-service limit on the endpoints that call Gemini or
speech, so nobody (a script, a crawler, a loop) can run up AI usage on our
project. No login needed: visitors are told apart by IP address.

In memory, per Cloud Run instance (the service runs at most 3), so the real
ceiling is a few times these numbers. A request over the limit gets 429 and
never reaches Gemini.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

# Paths that call Gemini, Speech or Text-to-Speech.
LIMITED_PREFIXES = ("/agent/turn", "/agent/live", "/speech", "/listings/draft", "/farmers/")
LIMITED_SUFFIXES = ("/no-burn-proof",)
PER_VISITOR_PER_MINUTE = 20
PER_VISITOR_PER_HOUR = 200
SERVICE_PER_HOUR = 1500          # all visitors together, per instance
MAX_UPLOAD_BYTES = 5_000_000

_visits: dict[str, deque] = defaultdict(deque)
_all: deque = deque()


def is_limited(path: str, method: str) -> bool:
    if method not in ("POST", "GET") or path.startswith("/farmers/") and not path.endswith(LIMITED_SUFFIXES):
        return False
    return path.startswith(LIMITED_PREFIXES) or path.endswith(LIMITED_SUFFIXES)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown"))


def _trim(q: deque, window: float, now: float) -> None:
    while q and now - q[0] > window:
        q.popleft()


def check(ip: str, now: float | None = None) -> str | None:
    """None if the request may go ahead (and is counted), else why not."""
    now = time.monotonic() if now is None else now
    mine = _visits[ip]
    _trim(mine, 3600, now)
    _trim(_all, 3600, now)
    if len(_all) >= SERVICE_PER_HOUR:
        return "The service is busy; please try again in a little while."
    if len(mine) >= PER_VISITOR_PER_HOUR:
        return "Too many requests from your connection this hour; please try again later."
    if sum(1 for t in mine if now - t <= 60) >= PER_VISITOR_PER_MINUTE:
        return "Too many requests in a minute; please slow down."
    mine.append(now)
    _all.append(now)
    return None


async def limit_middleware(request: Request, call_next):
    if request.url.path != "/agent/live" and is_limited(request.url.path, request.method):
        why = check(client_ip(request))
        if why:
            return JSONResponse({"detail": why}, status_code=429, headers={"Retry-After": "30"})
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES * 2:
            return JSONResponse({"detail": "That upload is too large."}, status_code=413)
    return await call_next(request)


def reset() -> None:
    """For tests."""
    _visits.clear()
    _all.clear()
