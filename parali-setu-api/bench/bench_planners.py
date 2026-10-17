"""Benchmark: the three OR-Tools planners against how it is done by hand.

Runs offline (no Google Cloud calls, no cost). For each season size it builds
the same farms, depots and crews the demo uses (5 depots, own crews from
reset_demo.DEPOTS, 8 on-call crews each) and plans pickups three ways:

- OR-Tools routing (scheduler.plan_pickups, the production code, same 2 s
  limit per pass that pickups.plan_depot uses)
- "nearest farm next": each crew drives to the closest farm that is ready,
  the way a dispatcher with a map would
- "most urgent next": each crew takes the farm with the closest sowing
  date, then the nearest -- a careful dispatcher

All three use own crews first and on-call crews only for what is left, with
the same shift, baling speed, travel model and capacity. Measured: farms
cleared before sowing, on-call crew-days hired, km driven, solve time.

It also times the procurement and delivery LPs at the demo's full scale.

    python -m bench.bench_planners            # writes bench/results/planners.json
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import reset_demo  # noqa: E402
from costs import OWN_COLLECTION_PER_T_INR, PARTNER_COLLECTION_PER_T_INR, road_km  # noqa: E402
from geo import DISTRICT_COORDS, haversine_km  # noqa: E402
from scheduler import (  # noqa: E402
    BALING_ACRES_PER_HOUR, HORIZON_DAYS, ROAD_FACTOR, STRAW_T_PER_ACRE, Crew, PickupJob, plan_pickups,
    service_minutes, travel_minutes,
)

START = date(2026, 10, 27)          # near the season peak
SIZES = (50, 100, 200, 400)
SEEDS = (1, 2, 3)                   # three different seasons per size
TIME_LIMIT_S = 2                    # what pickups.plan_depot uses in production
OUT = ROOT / "bench" / "results" / "planners.json"

# Districts weighted by how many demo farms each has (reset_demo.LISTINGS_PER_DISTRICT).
DISTRICT_WEIGHTS = reset_demo.LISTINGS_PER_DISTRICT


def build_depots_and_crews() -> tuple[list[dict], list[Crew]]:
    depots, crews = [], []
    for depot_id, name, district, capacity, radius, own in reset_demo.DEPOTS:
        lat, lon = DISTRICT_COORDS[district]
        depots.append({"id": depot_id, "lat": lat, "lon": lon, "radius_km": radius})
        crews += [Crew(f"{depot_id}_crew{k + 1}", depot_id, lat, lon) for k in range(own)]
        crews += [Crew(f"{depot_id}_oncall{k + 1}", depot_id, lat, lon, partner=True)
                  for k in range(reset_demo.ONCALL_CREWS_PER_DEPOT)]
    return depots, crews


def build_farms(n: int, seed: int, depots: list[dict]) -> list[PickupJob]:
    """n farms around the demo districts, sized and timed like the demo seed:
    4-14 acres, ready within 3 days, sowing 4-9 days after ready."""
    rng = random.Random(seed)
    names = list(DISTRICT_WEIGHTS)
    weights = [DISTRICT_WEIGHTS[d] for d in names]
    jobs = []
    while len(jobs) < n:
        district = rng.choices(names, weights)[0]
        lat0, lon0 = DISTRICT_COORDS[district]
        lat, lon = lat0 + rng.uniform(-0.15, 0.15), lon0 + rng.uniform(-0.15, 0.15)
        in_reach = [d for d in depots if road_km(lat, lon, d["lat"], d["lon"]) <= d["radius_km"]]
        if not in_reach:
            continue
        depot = min(in_reach, key=lambda d: road_km(lat, lon, d["lat"], d["lon"]))
        ready = START + timedelta(days=rng.randint(0, 3))
        sowing = ready + timedelta(days=rng.randint(4, 9))
        jobs.append(PickupJob(f"farm{len(jobs)}", depot["id"], round(lat, 5), round(lon, 5),
                              float(rng.choice([4, 5, 6, 7, 8, 9, 10, 11, 12, 14])), ready, sowing - timedelta(days=1)))
    return jobs


# ---- the hand-dispatch baselines -------------------------------------------

@dataclass
class Visit:
    crew_id: str
    partner: bool
    day: int
    booking_id: str
    acres: float
    lat: float
    lon: float


def greedy(jobs: list[PickupJob], crews: list[Crew], rule: str) -> list[Visit]:
    """Day by day, crew by crew: drive to the next farm by `rule`, bale what
    the crew-day still has room and time for (a farm can take several
    visits), go home when nothing more fits. Own crews first, then on-call."""
    left = {j.booking_id: j.acres for j in jobs}
    by_id = {j.booking_id: j for j in jobs}
    visits: list[Visit] = []
    for partner_pass in (False, True):
        for d in range(HORIZON_DAYS):
            day = START + timedelta(days=d)
            for crew in (c for c in crews if c.partner == partner_pass):
                pos, t, room = (crew.depot_lat, crew.depot_lon), crew.shift_start_min, crew.acres_per_day
                while room > 0.01:
                    open_jobs = [j for j in jobs if j.depot_id == crew.depot_id and left[j.booking_id] > 0.01
                                 and j.earliest <= day <= j.latest]
                    if not open_jobs:
                        break
                    if rule == "nearest":
                        open_jobs.sort(key=lambda j: haversine_km(*pos, j.lat, j.lon))
                    else:
                        open_jobs.sort(key=lambda j: (j.latest, haversine_km(*pos, j.lat, j.lon)))
                    placed = False
                    for j in open_jobs:
                        go = travel_minutes(*pos, j.lat, j.lon)
                        back = travel_minutes(j.lat, j.lon, crew.depot_lat, crew.depot_lon)
                        minutes_free = crew.shift_end_min - t - go - back
                        acres = min(left[j.booking_id], room, minutes_free * BALING_ACRES_PER_HOUR / 60)
                        if acres < min(left[j.booking_id], 1.0):   # not even a useful part-visit fits
                            continue
                        acres = round(acres, 2)
                        t += go + service_minutes(acres)
                        room -= acres
                        left[j.booking_id] -= acres
                        pos = (j.lat, j.lon)
                        visits.append(Visit(crew.id, crew.partner, d, j.booking_id, acres, j.lat, j.lon))
                        placed = True
                        break
                    if not placed:
                        break
    return visits


# ---- scoring, the same for every method ------------------------------------

def score(jobs: list[PickupJob], crews: list[Crew], visits: list[Visit], seconds: float) -> dict:
    crew_by_id = {c.id: c for c in crews}
    done: dict[str, float] = {}
    for v in visits:
        done[v.booking_id] = done.get(v.booking_id, 0.0) + v.acres
    cleared = [j for j in jobs if done.get(j.booking_id, 0.0) >= j.acres - 0.05]
    routes: dict[tuple[str, int], list[Visit]] = {}
    for v in visits:
        routes.setdefault((v.crew_id, v.day), []).append(v)
    km = 0.0
    for (crew_id, _), stops in routes.items():
        c = crew_by_id[crew_id]
        pts = [(c.depot_lat, c.depot_lon), *[(s.lat, s.lon) for s in stops], (c.depot_lat, c.depot_lon)]
        km += sum(haversine_km(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1)) * ROAD_FACTOR
    oncall_days = len({k for k in routes if crew_by_id[k[0]].partner})
    oncall_acres = sum(v.acres for v in visits if v.partner)
    total_acres = sum(j.acres for j in jobs)
    return {
        "farms": len(jobs), "acres": round(total_acres, 1),
        "cleared_pct": round(100 * len(cleared) / len(jobs), 1),
        "acres_cleared_pct": round(100 * sum(min(done.get(j.booking_id, 0), j.acres) for j in jobs) / total_acres, 1),
        "crew_days": len(routes), "oncall_crew_days": oncall_days,
        "oncall_share_pct": round(100 * oncall_acres / max(1e-9, sum(v.acres for v in visits)), 1),
        "km": round(km, 0), "km_per_acre": round(km / max(1e-9, sum(v.acres for v in visits)), 2),
        # On-call crews cost the market baling rate; ours cost OWN_COLLECTION_PER_T_INR.
        "extra_oncall_cost_inr": round(oncall_acres * STRAW_T_PER_ACRE * (PARTNER_COLLECTION_PER_T_INR - OWN_COLLECTION_PER_T_INR)),
        "solve_s": round(seconds, 2),
    }


def ortools(jobs: list[PickupJob], crews: list[Crew]) -> tuple[list[Visit], float]:
    """Production planning: one plan per depot, as pickups.plan_depot does."""
    crew_by_id = {c.id: c for c in crews}
    by_id = {j.booking_id: j for j in jobs}
    visits, seconds = [], 0.0
    for depot_id in sorted({j.depot_id for j in jobs}):
        started = time.perf_counter()
        result = plan_pickups([j for j in jobs if j.depot_id == depot_id], [c for c in crews if c.depot_id == depot_id],
                              START, horizon_days=HORIZON_DAYS, time_limit_seconds=TIME_LIMIT_S)
        seconds += time.perf_counter() - started
        routes = sorted(result.assignments, key=lambda a: (a.day, a.crew_id, a.sequence))
        for a in routes:
            j = by_id[a.booking_id]
            visits.append(Visit(a.crew_id, crew_by_id[a.crew_id].partner, (a.day - START).days, a.booking_id,
                                a.acres, j.lat, j.lon))
    return visits, seconds


def bench_routing() -> list[dict]:
    depots, crews = build_depots_and_crews()
    rows = []
    for n in SIZES:
        for seed in SEEDS:
            jobs = build_farms(n, seed, depots)
            for method in ("ortools", "nearest", "urgent"):
                if method == "ortools":
                    visits, secs = ortools(jobs, crews)
                else:
                    started = time.perf_counter()
                    visits = greedy(jobs, crews, method)
                    secs = time.perf_counter() - started
                row = {"method": method, "seed": seed, **score(jobs, crews, visits, secs)}
                rows.append(row)
                print(f"{n:>4} farms seed {seed} {method:<8} cleared {row['cleared_pct']:5.1f}%  "
                      f"on-call days {row['oncall_crew_days']:>3}  km {row['km']:>7.0f}  {row['solve_s']:.2f}s", flush=True)
    return rows


def summarise(rows: list[dict]) -> list[dict]:
    out = []
    for n in SIZES:
        for method in ("ortools", "nearest", "urgent"):
            sel = [r for r in rows if r["farms"] == n and r["method"] == method]
            out.append({"farms": n, "method": method, **{k: round(statistics.mean(r[k] for r in sel), 2) for k in
                        ("cleared_pct", "acres_cleared_pct", "crew_days", "oncall_crew_days", "oncall_share_pct",
                         "km", "km_per_acre", "extra_oncall_cost_inr", "solve_s")}})
    return out


# ---- the two LPs at demo scale ---------------------------------------------

def bench_lps() -> dict:
    import json as _json

    import operations
    import pickups
    from fakes import use_fake_firestore

    import pytest
    patcher = pytest.MonkeyPatch()
    db = use_fake_firestore(patcher)
    db.collection("forecasts").document("supply_live_2026").set(
        _json.loads((ROOT / "forecast" / "data" / "results" / "supply_live_2026.json").read_text(encoding="utf-8")))
    today = date(2026, 10, 17)
    reset_demo.seed_depots(db)
    operations.run_procurement(db, today)
    reset_demo.seed_customers_and_orders(db, today)

    import procurement
    import deliveries
    timings = {"procurement": [], "deliveries": []}
    sizes = {}
    real_proc, real_del = procurement.plan_procurement, deliveries.plan_deliveries

    def timed(name, fn):
        def wrapper(*a, **k):
            started = time.perf_counter()
            out = fn(*a, **k)
            timings[name].append(time.perf_counter() - started)
            return out
        return wrapper

    patcher.setattr(operations, "plan_procurement", timed("procurement", real_proc))
    patcher.setattr(operations, "plan_deliveries", timed("deliveries", real_del))
    for _ in range(5):
        plan = operations.run_procurement(db, today, repost_today=True)
        dplan = operations.run_deliveries(db, today)
    sizes["procurement"] = {"districts": len(plan["districts"]), "weeks": len(plan["weeks"]),
                            "depots": len(plan["depot_intake"]), "status": plan["status"]}
    sizes["deliveries"] = {"months": len(dplan["months"]), "orders": len(store_orders(db)), "status": dplan["status"]}
    patcher.undo()
    return {k: {"median_ms": round(statistics.median(v) * 1000, 1), "max_ms": round(max(v) * 1000, 1),
                "runs": len(v), **sizes[k]} for k, v in timings.items()}


def store_orders(db):
    import firestore_store as store
    return store.get_orders(db)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="*", default=list(SIZES))
    parser.add_argument("--seeds", type=int, nargs="*", default=list(SEEDS))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    SIZES, SEEDS, OUT = tuple(args.sizes), tuple(args.seeds), Path(args.out)
    sys.path.insert(0, str(ROOT / "tests"))
    rows = bench_routing()
    lps = bench_lps()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"start": START.isoformat(), "seeds": SEEDS, "time_limit_s": TIME_LIMIT_S,
                               "routing_runs": rows, "routing_summary": summarise(rows), "lps": lps,
                               "ran_at": time.strftime("%Y-%m-%d %H:%M")}, indent=2), encoding="utf-8")
    print(json.dumps(summarise(rows), indent=1))
    print(json.dumps(lps, indent=1))
