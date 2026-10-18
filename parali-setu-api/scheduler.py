"""Pickup scheduling: turns bookings into guaranteed pickup slots.

The procurement planner (procurement.py) decides how much straw to buy where
and which depot each district feeds. This module decides *when* and *by whom*
each booked farm is collected: a capacitated vehicle routing problem with time
windows, solved with OR-Tools routing.

Model
- A vehicle is one crew on one day of the planning horizon (a "crew-day").
  It leaves its Parali Setu depot after the shift starts and must be back
  before it ends.
- A node is one farm visit. Its load is the acres to bale, its service time
  is acres / BALING_ACRES_PER_HOUR, and its time window runs from the start
  of its ready day to the end of its last allowed day (the day before
  sowing). A farm bigger than a crew-day's capacity is split into
  day-sized visits.
- A visit may only use crews of the depot it was booked into.
- On-call crews (hired balers) are planned in a second pass, only for farms
  our own crews could not fit before sowing. This is what lets every booking
  get a slot, and it keeps the extra cost visible: ops can see exactly which
  pickups needed a hired crew.
- A locked slot (one the farmer accepted) pins the visit to that crew-day
  and that arrival window; everything else is planned around it.
- Every visit carries a large drop penalty, so the solver drops one only
  when it cannot be served; dropped visits are reported with a reason, never
  silently lost.

Gemini never touches this file. Every slot a farmer is shown comes from here.
Planning assumptions are constants below and are stated in the README.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from geo import haversine_km

STRAW_T_PER_ACRE = 1.75          # Hindustan Times: 17-18 quintals per acre
BALING_ACRES_PER_HOUR = 2.0      # assumption, verify before the deck
DEFAULT_ACRES_PER_CREW_DAY = 20.0
ROAD_FACTOR = 1.3                # straight line -> road distance
TRAVEL_KMH = 30.0
DEFAULT_SHIFT_START_MIN = 7 * 60
DEFAULT_SHIFT_END_MIN = 18 * 60
HORIZON_DAYS = 10
SLOT_WINDOW_MIN = 180            # farmers are promised a 3-hour arrival window
MINUTES_PER_DAY = 24 * 60

_ACRE_SCALE = 100                # OR-Tools dimensions are integers
# Leaving a visit unplanned costs in proportion to its acres. A flat penalty
# made the solver keep many small visits and drop the big ones, which then
# went to hired crews: the benchmark (bench/bench_planners.py) caught it
# hiring more on-call crew-days than a nearest-farm-first dispatcher at peak.
_DROP_PENALTY_PER_ACRE = 1_000_000
_LOCKED_DROP_PENALTY = 1_000_000_000
_EARLY_DAY_COST = 50             # small nudge toward earlier pickups
# A hired crew-day is real money (the market baling rate over our own cost),
# so using one more must save at least a shift's worth of driving. Without it
# the solver spread work thinly over extra hired crews to shave minutes.
_ONCALL_DAY_COST = 600
SAFETY_TIME_LIMIT_SECONDS = 10
FIRST_SOLUTION_STRATEGY = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

REASON_DEADLINE_PASSED = "The sowing deadline has already passed."
REASON_NO_CREWS = "This depot has no pickup crews."
REASON_NO_CAPACITY = "Our crews don't have enough capacity before the sowing deadline."
REASON_BOOKED = "Our crews are fully booked before the sowing deadline."
REASON_LOCK_LOST = "The accepted slot could no longer be kept."
REASON_BEYOND_HORIZON = "The stubble is ready after the current planning window; it will be planned in a later run."
REASON_TOO_FAR = "The farm is too far from the depot for a crew to reach, bale and return within a shift."

# Stable codes for each reason, so the farmer app can say it in Punjabi or
# Hindi instead of showing this English text.
REASON_CODES = {
    REASON_DEADLINE_PASSED: "deadline_passed", REASON_NO_CREWS: "no_crews",
    REASON_NO_CAPACITY: "no_capacity", REASON_BOOKED: "booked",
    REASON_LOCK_LOST: "lock_lost", REASON_BEYOND_HORIZON: "beyond_horizon", REASON_TOO_FAR: "too_far",
}


def reason_code(reason: str | None) -> str | None:
    return REASON_CODES.get(reason) if reason else None


@dataclass(frozen=True)
class Crew:
    id: str
    depot_id: str
    depot_lat: float
    depot_lon: float
    shift_start_min: int = DEFAULT_SHIFT_START_MIN
    shift_end_min: int = DEFAULT_SHIFT_END_MIN
    acres_per_day: float = DEFAULT_ACRES_PER_CREW_DAY
    partner: bool = False       # a hired baler crew, used only when ours can't make it


@dataclass(frozen=True)
class LockedSlot:
    crew_id: str
    day: date
    window_start_min: int
    window_end_min: int


@dataclass(frozen=True)
class PickupJob:
    booking_id: str
    depot_id: str
    lat: float
    lon: float
    acres: float
    earliest: date      # ready date
    latest: date        # last allowed pickup day (day before sowing)
    locked: LockedSlot | None = None
    not_before_min: int = 0   # on the earliest day, no start before this minute (24 hours' notice)


@dataclass(frozen=True)
class Assignment:
    booking_id: str
    visit: int
    crew_id: str
    day: date
    start_min: int          # planned arrival, minutes after midnight
    end_min: int            # planned finish
    window_start_min: int   # promised arrival window
    window_end_min: int
    sequence: int           # order within the crew's day
    acres: float


@dataclass
class ScheduleResult:
    assignments: list[Assignment]
    unschedulable: list[dict]   # {"booking_id", "reason"}

    def slots_for(self, booking_id: str) -> list[Assignment]:
        return sorted((a for a in self.assignments if a.booking_id == booking_id), key=lambda a: (a.day, a.start_min))


def acres_from_kg(kg: float) -> float:
    return round(kg / (STRAW_T_PER_ACRE * 1000), 2)


def service_minutes(acres: float) -> int:
    return max(15, math.ceil(acres / BALING_ACRES_PER_HOUR * 60))


def travel_minutes(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    return math.ceil(haversine_km(lat1, lon1, lat2, lon2) * ROAD_FACTOR / TRAVEL_KMH * 60)


def promised_window(start_min: int, shift_end_min: int) -> tuple[int, int]:
    """The arrival window shown to a farmer: the planned start rounded down
    to the hour, three hours wide, never past the end of the shift."""
    window_start = (start_min // 60) * 60
    return window_start, min(window_start + SLOT_WINDOW_MIN, shift_end_min)


def max_visit_acres(job: PickupJob, depot_crews: list[Crew]) -> float:
    """The most one visit can bale: a crew-day's acre capacity, and what fits
    in a shift after driving there and back. A distant farm is split into
    several day-sized visits; 0 means not even a small visit fits."""
    best = 0.0
    for c in depot_crews:
        round_trip = 2 * travel_minutes(c.depot_lat, c.depot_lon, job.lat, job.lon)
        work_min = c.shift_end_min - c.shift_start_min - round_trip
        best = max(best, min(c.acres_per_day, work_min * BALING_ACRES_PER_HOUR / 60))
    return round(max(0.0, best) * 0.95, 2)   # a little slack so the visit fits the time dimension


def _split_visits(job: PickupJob, max_crew_acres: float) -> list[float]:
    if job.acres <= max_crew_acres or max_crew_acres <= 0:
        return [job.acres]
    count = math.ceil(job.acres / max_crew_acres)
    base = round(job.acres / count, 2)
    visits = [base] * (count - 1)
    visits.append(round(job.acres - base * (count - 1), 2))
    return visits


# Reasons a hired crew can fix; a passed deadline or a lost lock it cannot.
_PARTNER_CAN_HELP = {REASON_BOOKED, REASON_NO_CAPACITY, REASON_NO_CREWS}


def plan_pickups(
    jobs: list[PickupJob],
    crews: list[Crew],
    start: date,
    horizon_days: int = HORIZON_DAYS,
    time_limit_seconds: int = 3,
    not_before_min_today: int | None = None,
    used_acres: dict[tuple[str, date], float] | None = None,
) -> ScheduleResult:
    """Plans every job over [start, start + horizon_days). Deterministic when
    time_limit_seconds is 0 (first solution only, used by tests).

    `used_acres` is work already done on a crew-day (farms collected today),
    which that crew-day can no longer offer to new farms.

    Two passes: our own crews first, then on-call crews for whatever our
    crews could not fit. A slot locked onto an on-call crew stays with it.

    `not_before_min_today` (minutes after midnight, local time) keeps crews
    on day 0 from being planned before that time, so a farmer is never
    offered a slot that has already passed."""
    kwargs = dict(horizon_days=horizon_days, time_limit_seconds=time_limit_seconds,
                  not_before_min_today=not_before_min_today, used_acres=used_acres or {})
    partners = [c for c in crews if c.partner]
    partner_ids = {c.id for c in partners}
    on_partner_lock = {j.booking_id for j in jobs if j.locked is not None and j.locked.crew_id in partner_ids}
    first = _plan_with([j for j in jobs if j.booking_id not in on_partner_lock],
                       [c for c in crews if not c.partner], start, **kwargs)
    if not partners:
        return first
    retry = {u["booking_id"] for u in first.unschedulable if u["reason"] in _PARTNER_CAN_HELP} | on_partner_lock
    second = _plan_with([j for j in jobs if j.booking_id in retry], partners, start, **kwargs)
    assignments = sorted(first.assignments + second.assignments, key=lambda a: (a.day, a.crew_id, a.sequence))
    unschedulable = [u for u in first.unschedulable if u["booking_id"] not in retry] + second.unschedulable
    return ScheduleResult(assignments, unschedulable)


def _plan_with(
    jobs: list[PickupJob],
    crews: list[Crew],
    start: date,
    horizon_days: int,
    time_limit_seconds: int,
    not_before_min_today: int | None,
    used_acres: dict[tuple[str, date], float],
) -> ScheduleResult:
    unschedulable: list[dict] = []
    crews_by_depot: dict[str, list[Crew]] = {}
    for crew in crews:
        crews_by_depot.setdefault(crew.depot_id, []).append(crew)

    # Vehicles: one per crew per day.
    vehicles: list[tuple[Crew, int]] = [(crew, d) for crew in crews for d in range(horizon_days)]
    vehicle_index = {(crew.id, d): v for v, (crew, d) in enumerate(vehicles)}

    def allowed_vehicles(job: PickupJob) -> list[int]:
        if job.locked is not None:
            v = vehicle_index.get((job.locked.crew_id, (job.locked.day - start).days))
            return [] if v is None else [v]
        first_day = max(0, (job.earliest - start).days)
        last_day = min(horizon_days - 1, (job.latest - start).days)
        return [vehicle_index[(c.id, d)] for c in crews_by_depot[job.depot_id] for d in range(first_day, last_day + 1)]

    # Jobs with no valid crew-day are reported here and never reach the
    # model (in OR-Tools an empty allowed-vehicle set can mean "any vehicle").
    candidates: list[PickupJob] = []
    allowed_by_job: dict[str, list[int]] = {}
    visit_cap: dict[str, float] = {}
    for job in jobs:
        depot_crews = crews_by_depot.get(job.depot_id) or []
        if depot_crews:
            visit_cap[job.booking_id] = max_visit_acres(job, depot_crews)
        if job.latest < start or job.latest < job.earliest:
            unschedulable.append({"booking_id": job.booking_id, "reason": REASON_DEADLINE_PASSED})
        elif not crews_by_depot.get(job.depot_id):
            unschedulable.append({"booking_id": job.booking_id, "reason": REASON_NO_CREWS})
        elif job.locked is None and visit_cap[job.booking_id] <= 0:
            unschedulable.append({"booking_id": job.booking_id, "reason": REASON_TOO_FAR})
        elif not (allowed := allowed_vehicles(job)):
            reason = REASON_LOCK_LOST if job.locked is not None else REASON_BEYOND_HORIZON
            unschedulable.append({"booking_id": job.booking_id, "reason": reason})
        else:
            candidates.append(job)
            allowed_by_job[job.booking_id] = allowed
    if not candidates:
        return ScheduleResult([], unschedulable)

    # Nodes: one depot per crew, then one node per visit.
    depot_node = {crew.id: i for i, crew in enumerate(crews)}
    points: list[tuple[float, float]] = [(c.depot_lat, c.depot_lon) for c in crews]
    service: list[int] = [0] * len(crews)
    load: list[int] = [0] * len(crews)
    visits: list[tuple[PickupJob, int, float]] = []   # (job, visit number, acres)
    for job in candidates:
        max_acres = job.acres if job.locked is not None else visit_cap[job.booking_id]
        for k, acres in enumerate(_split_visits(job, max_acres)):
            visits.append((job, k, acres))
            points.append((job.lat, job.lon))
            service.append(service_minutes(acres))
            load.append(int(round(acres * _ACRE_SCALE)))

    n = len(points)
    travel = [[0 if i == j else travel_minutes(*points[i], *points[j]) for j in range(n)] for i in range(n)]

    manager = pywrapcp.RoutingIndexManager(n, len(vehicles), [depot_node[c.id] for c, _ in vehicles],
                                           [depot_node[c.id] for c, _ in vehicles])
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index: int, to_index: int) -> int:
        i, j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        return service[i] + travel[i][j]

    transit_cb = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)
    horizon_minutes = horizon_days * MINUTES_PER_DAY
    routing.AddDimension(transit_cb, MINUTES_PER_DAY, horizon_minutes, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    load_cb = routing.RegisterUnaryTransitCallback(lambda index: load[manager.IndexToNode(index)])
    routing.AddDimensionWithVehicleCapacity(
        load_cb, 0, [int(round(max(0.0, c.acres_per_day - used_acres.get((c.id, start + timedelta(days=d)), 0.0)) * _ACRE_SCALE))
                     for c, d in vehicles], True, "Acres")

    for v, (crew, d) in enumerate(vehicles):
        day0 = d * MINUTES_PER_DAY
        shift_start = crew.shift_start_min
        if d == 0 and not_before_min_today is not None:
            shift_start = min(max(shift_start, not_before_min_today), crew.shift_end_min)
        time_dim.CumulVar(routing.Start(v)).SetRange(day0 + shift_start, day0 + crew.shift_end_min)
        time_dim.CumulVar(routing.End(v)).SetRange(day0 + crew.shift_start_min, day0 + crew.shift_end_min)
        routing.SetFixedCostOfVehicle(_EARLY_DAY_COST * (d + 1) + (_ONCALL_DAY_COST if crew.partner else 0), v)

    for k, (job, _, acres) in enumerate(visits):
        index = manager.NodeToIndex(len(crews) + k)
        # Restrict the visit's vehicle variable directly (-1 = left unvisited,
        # which the disjunction below prices). This OR-Tools build doesn't
        # accept a Python list in SetAllowedVehiclesForIndex.
        routing.VehicleVar(index).SetValues([-1, *allowed_by_job[job.booking_id]])
        if job.locked is not None:
            day0 = (job.locked.day - start).days * MINUTES_PER_DAY
            time_dim.CumulVar(index).SetRange(day0 + job.locked.window_start_min, day0 + job.locked.window_end_min)
            routing.AddDisjunction([index], _LOCKED_DROP_PENALTY)
        else:
            first_day = max(0, (job.earliest - start).days)
            last_day = min(horizon_days - 1, (job.latest - start).days)
            not_before = job.not_before_min if (job.earliest - start).days == first_day else 0
            time_dim.CumulVar(index).SetRange(first_day * MINUTES_PER_DAY + not_before, (last_day + 1) * MINUTES_PER_DAY - 1)
            routing.AddDisjunction([index], int(_DROP_PENALTY_PER_ACRE * max(1.0, acres)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = FIRST_SOLUTION_STRATEGY
    if time_limit_seconds > 0:
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = time_limit_seconds
    else:
        # Deterministic mode: stop at the first solution. Without this,
        # default local search runs to a local optimum, which takes minutes
        # with dozens of crew-days.
        params.solution_limit = 1
        params.time_limit.seconds = SAFETY_TIME_LIMIT_SECONDS
    solution = routing.SolveWithParameters(params)

    assignments: list[Assignment] = []
    if solution is not None:
        for v, (crew, d) in enumerate(vehicles):
            index = solution.Value(routing.NextVar(routing.Start(v)))
            sequence = 0
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                job, visit_no, acres = visits[node - len(crews)]
                arrival = solution.Value(time_dim.CumulVar(index)) - d * MINUTES_PER_DAY
                sequence += 1
                if job.locked is not None:
                    window = (job.locked.window_start_min, job.locked.window_end_min)
                else:
                    window = promised_window(arrival, crew.shift_end_min)
                assignments.append(Assignment(
                    booking_id=job.booking_id, visit=visit_no, crew_id=crew.id, day=start + timedelta(days=d),
                    start_min=arrival, end_min=arrival + service[node],
                    window_start_min=window[0], window_end_min=window[1], sequence=sequence, acres=acres))
                index = solution.Value(routing.NextVar(index))

    # A job is only scheduled if every one of its visits is; otherwise it is
    # reported with the most specific reason we can give.
    visits_per_job: dict[str, int] = {}
    for job, _, _ in visits:
        visits_per_job[job.booking_id] = visits_per_job.get(job.booking_id, 0) + 1
    placed: dict[str, int] = {}
    for a in assignments:
        placed[a.booking_id] = placed.get(a.booking_id, 0) + 1
    incomplete = {mid for mid, count in visits_per_job.items() if placed.get(mid, 0) < count}
    assignments = [a for a in assignments if a.booking_id not in incomplete]
    for job in candidates:
        if job.booking_id not in incomplete:
            continue
        unschedulable.append({"booking_id": job.booking_id, "reason": _drop_reason(job, crews_by_depot[job.depot_id], start, horizon_days)})

    assignments.sort(key=lambda a: (a.day, a.crew_id, a.sequence))
    return ScheduleResult(assignments, unschedulable)


def _drop_reason(job: PickupJob, depot_crews: list[Crew], start: date, horizon_days: int) -> str:
    if job.locked is not None:
        return REASON_LOCK_LOST
    first_day = max(0, (job.earliest - start).days)
    last_day = min(horizon_days - 1, (job.latest - start).days)
    days = max(0, last_day - first_day + 1)
    capacity = days * sum(c.acres_per_day for c in depot_crews)
    return REASON_NO_CAPACITY if capacity < job.acres else REASON_BOOKED
