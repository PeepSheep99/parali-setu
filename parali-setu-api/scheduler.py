"""Pickup scheduling: turns matches into guaranteed pickup slots.

The matching LP (solver.py) decides which buyer takes which listing. This
module decides *when* and *by whom* it is collected: a capacitated vehicle
routing problem with time windows, solved with OR-Tools routing.

Model
- A vehicle is one crew on one day of the planning horizon (a "crew-day").
  It leaves the buyer's collection depot after the shift starts and must be
  back before it ends.
- A node is one farm visit. Its load is the acres to bale, its service time
  is acres / BALING_ACRES_PER_HOUR, and its time window runs from the start
  of its ready day to the end of its last allowed day (the day before
  sowing). A farm bigger than a crew-day's capacity is split into
  day-sized visits.
- A visit may only use crews of the buyer it was matched to.
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
_DROP_PENALTY = 10_000_000
_LOCKED_DROP_PENALTY = 1_000_000_000
_EARLY_DAY_COST = 50             # small nudge toward earlier pickups
SAFETY_TIME_LIMIT_SECONDS = 10
FIRST_SOLUTION_STRATEGY = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

REASON_DEADLINE_PASSED = "The sowing deadline has already passed."
REASON_NO_CREWS = "This buyer has no pickup crews."
REASON_NO_CAPACITY = "The buyer's crews don't have enough capacity before the sowing deadline."
REASON_BOOKED = "The buyer's crews are fully booked before the sowing deadline."
REASON_LOCK_LOST = "The accepted slot could no longer be kept."
REASON_BEYOND_HORIZON = "The stubble is ready after the current planning window; it will be planned in a later run."


@dataclass(frozen=True)
class Crew:
    id: str
    company_id: str
    depot_lat: float
    depot_lon: float
    shift_start_min: int = DEFAULT_SHIFT_START_MIN
    shift_end_min: int = DEFAULT_SHIFT_END_MIN
    acres_per_day: float = DEFAULT_ACRES_PER_CREW_DAY


@dataclass(frozen=True)
class LockedSlot:
    crew_id: str
    day: date
    window_start_min: int
    window_end_min: int


@dataclass(frozen=True)
class PickupJob:
    match_id: str
    company_id: str
    lat: float
    lon: float
    acres: float
    earliest: date      # ready date
    latest: date        # last allowed pickup day (day before sowing)
    locked: LockedSlot | None = None


@dataclass(frozen=True)
class Assignment:
    match_id: str
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
    unschedulable: list[dict]   # {"match_id", "reason"}

    def slots_for(self, match_id: str) -> list[Assignment]:
        return sorted((a for a in self.assignments if a.match_id == match_id), key=lambda a: (a.day, a.start_min))


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


def _split_visits(job: PickupJob, max_crew_acres: float) -> list[float]:
    if job.acres <= max_crew_acres or max_crew_acres <= 0:
        return [job.acres]
    count = math.ceil(job.acres / max_crew_acres)
    base = round(job.acres / count, 2)
    visits = [base] * (count - 1)
    visits.append(round(job.acres - base * (count - 1), 2))
    return visits


def plan_pickups(
    jobs: list[PickupJob],
    crews: list[Crew],
    start: date,
    horizon_days: int = HORIZON_DAYS,
    time_limit_seconds: int = 3,
    not_before_min_today: int | None = None,
) -> ScheduleResult:
    """Plans every job over [start, start + horizon_days). Deterministic when
    time_limit_seconds is 0 (first solution only, used by tests).

    `not_before_min_today` (minutes after midnight, local time) keeps crews
    on day 0 from being planned before that time, so a farmer is never
    offered a slot that has already passed."""
    unschedulable: list[dict] = []
    crews_by_company: dict[str, list[Crew]] = {}
    for crew in crews:
        crews_by_company.setdefault(crew.company_id, []).append(crew)

    # Vehicles: one per crew per day.
    vehicles: list[tuple[Crew, int]] = [(crew, d) for crew in crews for d in range(horizon_days)]
    vehicle_index = {(crew.id, d): v for v, (crew, d) in enumerate(vehicles)}

    def allowed_vehicles(job: PickupJob) -> list[int]:
        if job.locked is not None:
            v = vehicle_index.get((job.locked.crew_id, (job.locked.day - start).days))
            return [] if v is None else [v]
        first_day = max(0, (job.earliest - start).days)
        last_day = min(horizon_days - 1, (job.latest - start).days)
        return [vehicle_index[(c.id, d)] for c in crews_by_company[job.company_id] for d in range(first_day, last_day + 1)]

    # Jobs with no valid crew-day are reported here and never reach the
    # model (in OR-Tools an empty allowed-vehicle set can mean "any vehicle").
    candidates: list[PickupJob] = []
    allowed_by_job: dict[str, list[int]] = {}
    for job in jobs:
        if job.latest < start or job.latest < job.earliest:
            unschedulable.append({"match_id": job.match_id, "reason": REASON_DEADLINE_PASSED})
        elif not crews_by_company.get(job.company_id):
            unschedulable.append({"match_id": job.match_id, "reason": REASON_NO_CREWS})
        elif not (allowed := allowed_vehicles(job)):
            reason = REASON_LOCK_LOST if job.locked is not None else REASON_BEYOND_HORIZON
            unschedulable.append({"match_id": job.match_id, "reason": reason})
        else:
            candidates.append(job)
            allowed_by_job[job.match_id] = allowed
    if not candidates:
        return ScheduleResult([], unschedulable)

    # Nodes: one depot per crew, then one node per visit.
    depot_node = {crew.id: i for i, crew in enumerate(crews)}
    points: list[tuple[float, float]] = [(c.depot_lat, c.depot_lon) for c in crews]
    service: list[int] = [0] * len(crews)
    load: list[int] = [0] * len(crews)
    visits: list[tuple[PickupJob, int, float]] = []   # (job, visit number, acres)
    for job in candidates:
        max_acres = max(c.acres_per_day for c in crews_by_company[job.company_id])
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
        load_cb, 0, [int(round(c.acres_per_day * _ACRE_SCALE)) for c, _ in vehicles], True, "Acres")

    for v, (crew, d) in enumerate(vehicles):
        day0 = d * MINUTES_PER_DAY
        shift_start = crew.shift_start_min
        if d == 0 and not_before_min_today is not None:
            shift_start = min(max(shift_start, not_before_min_today), crew.shift_end_min)
        time_dim.CumulVar(routing.Start(v)).SetRange(day0 + shift_start, day0 + crew.shift_end_min)
        time_dim.CumulVar(routing.End(v)).SetRange(day0 + crew.shift_start_min, day0 + crew.shift_end_min)
        routing.SetFixedCostOfVehicle(_EARLY_DAY_COST * (d + 1), v)

    for k, (job, _, _) in enumerate(visits):
        index = manager.NodeToIndex(len(crews) + k)
        # Restrict the visit's vehicle variable directly (-1 = left unvisited,
        # which the disjunction below prices). This OR-Tools build doesn't
        # accept a Python list in SetAllowedVehiclesForIndex.
        routing.VehicleVar(index).SetValues([-1, *allowed_by_job[job.match_id]])
        if job.locked is not None:
            day0 = (job.locked.day - start).days * MINUTES_PER_DAY
            time_dim.CumulVar(index).SetRange(day0 + job.locked.window_start_min, day0 + job.locked.window_end_min)
            routing.AddDisjunction([index], _LOCKED_DROP_PENALTY)
        else:
            first_day = max(0, (job.earliest - start).days)
            last_day = min(horizon_days - 1, (job.latest - start).days)
            time_dim.CumulVar(index).SetRange(first_day * MINUTES_PER_DAY, (last_day + 1) * MINUTES_PER_DAY - 1)
            routing.AddDisjunction([index], _DROP_PENALTY)

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
                    match_id=job.match_id, visit=visit_no, crew_id=crew.id, day=start + timedelta(days=d),
                    start_min=arrival, end_min=arrival + service[node],
                    window_start_min=window[0], window_end_min=window[1], sequence=sequence, acres=acres))
                index = solution.Value(routing.NextVar(index))

    # A job is only scheduled if every one of its visits is; otherwise it is
    # reported with the most specific reason we can give.
    visits_per_job: dict[str, int] = {}
    for job, _, _ in visits:
        visits_per_job[job.match_id] = visits_per_job.get(job.match_id, 0) + 1
    placed: dict[str, int] = {}
    for a in assignments:
        placed[a.match_id] = placed.get(a.match_id, 0) + 1
    incomplete = {mid for mid, count in visits_per_job.items() if placed.get(mid, 0) < count}
    assignments = [a for a in assignments if a.match_id not in incomplete]
    for job in candidates:
        if job.match_id not in incomplete:
            continue
        unschedulable.append({"match_id": job.match_id, "reason": _drop_reason(job, crews_by_company[job.company_id], start, horizon_days)})

    assignments.sort(key=lambda a: (a.day, a.crew_id, a.sequence))
    return ScheduleResult(assignments, unschedulable)


def _drop_reason(job: PickupJob, company_crews: list[Crew], start: date, horizon_days: int) -> str:
    if job.locked is not None:
        return REASON_LOCK_LOST
    first_day = max(0, (job.earliest - start).days)
    last_day = min(horizon_days - 1, (job.latest - start).days)
    days = max(0, last_day - first_day + 1)
    capacity = days * sum(c.acres_per_day for c in company_crews)
    return REASON_NO_CAPACITY if capacity < job.acres else REASON_BOOKED
