"""Pickup scheduler tests: windows, capacity, buyer-owned crews, locked
slots, splitting, unschedulable reasons and determinism. All run the
deterministic first-solution mode (time_limit_seconds=0)."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo import DISTRICT_COORDS  # noqa: E402
from scheduler import (  # noqa: E402
    REASON_BOOKED,
    REASON_DEADLINE_PASSED,
    REASON_LOCK_LOST,
    REASON_NO_CAPACITY,
    REASON_NO_CREWS,
    Crew,
    LockedSlot,
    PickupJob,
    acres_from_kg,
    plan_pickups,
    promised_window,
    service_minutes,
)

START = date(2026, 10, 20)
SANGRUR = DISTRICT_COORDS["Sangrur"]
PATIALA = DISTRICT_COORDS["Patiala"]


def crew(cid="crew1", company="c1", acres=20.0, depot=SANGRUR):
    return Crew(id=cid, company_id=company, depot_lat=depot[0], depot_lon=depot[1], acres_per_day=acres)


def job(mid, acres=8.0, earliest=START, latest=None, company="c1", where=SANGRUR, locked=None):
    return PickupJob(match_id=mid, company_id=company, lat=where[0] + 0.02, lon=where[1] + 0.02, acres=acres,
                     earliest=earliest, latest=latest or earliest + timedelta(days=5), locked=locked)


def plan(jobs, crews, horizon=10):
    return plan_pickups(jobs, crews, START, horizon_days=horizon, time_limit_seconds=0)


def test_single_job_gets_a_slot_inside_window_and_shift():
    result = plan([job("m1", earliest=START + timedelta(days=2), latest=START + timedelta(days=4))], [crew()])
    assert result.unschedulable == []
    (a,) = result.assignments
    assert START + timedelta(days=2) <= a.day <= START + timedelta(days=4)
    assert 7 * 60 <= a.start_min and a.end_min <= 18 * 60
    assert a.window_start_min <= a.start_min <= a.window_end_min
    assert a.end_min - a.start_min == service_minutes(8.0)


def test_capacity_per_crew_day_is_respected_and_overflow_reported():
    """Three 8-acre farms that must all be done on the same single day with
    one 20-acre crew: two fit, one is reported -- never silently dropped."""
    jobs = [job(f"m{i}", earliest=START, latest=START) for i in range(3)]
    result = plan(jobs, [crew()])
    assert len(result.assignments) == 2
    assert result.unschedulable == [{"match_id": result.unschedulable[0]["match_id"], "reason": REASON_BOOKED}]
    assert sum(a.acres for a in result.assignments) <= 20.0


def test_spare_days_absorb_the_overflow():
    jobs = [job(f"m{i}", earliest=START, latest=START + timedelta(days=2)) for i in range(3)]
    result = plan(jobs, [crew()])
    assert result.unschedulable == []
    per_day = {}
    for a in result.assignments:
        per_day[a.day] = per_day.get(a.day, 0) + a.acres
    assert all(total <= 20.0 for total in per_day.values())


def test_only_the_matched_buyers_crews_are_used():
    crews = [crew("own", company="c1", depot=SANGRUR), crew("other", company="c2", depot=SANGRUR)]
    result = plan([job("m1", company="c1")], crews)
    assert {a.crew_id for a in result.assignments} == {"own"}


def test_deadline_passed_and_no_crews_are_reported_with_reasons():
    jobs = [
        job("late", earliest=START - timedelta(days=5), latest=START - timedelta(days=1)),
        job("orphan", company="no_fleet"),
    ]
    result = plan(jobs, [crew()])
    assert result.assignments == []
    reasons = {u["match_id"]: u["reason"] for u in result.unschedulable}
    assert reasons == {"late": REASON_DEADLINE_PASSED, "orphan": REASON_NO_CREWS}


def test_not_enough_capacity_in_window_says_so():
    result = plan([job("big", acres=50.0, earliest=START, latest=START)], [crew(acres=20.0)])
    assert result.unschedulable == [{"match_id": "big", "reason": REASON_NO_CAPACITY}]


def test_big_farm_is_split_into_day_sized_visits():
    result = plan([job("big", acres=45.0, earliest=START, latest=START + timedelta(days=4))], [crew(acres=20.0)])
    assert result.unschedulable == []
    visits = result.slots_for("big")
    assert len(visits) == 3
    assert abs(sum(v.acres for v in visits) - 45.0) < 0.01
    assert len({v.day for v in visits}) == 3, "one crew can only do one day-sized visit per day"


def test_locked_slot_stays_fixed_when_new_work_arrives():
    first = plan([job("m1", earliest=START, latest=START + timedelta(days=3))], [crew()])
    (a,) = first.assignments
    lock = LockedSlot(crew_id=a.crew_id, day=a.day, window_start_min=a.window_start_min, window_end_min=a.window_end_min)

    newcomers = [job(f"n{i}", earliest=START, latest=START + timedelta(days=3), where=PATIALA) for i in range(4)]
    second = plan([job("m1", earliest=START, latest=START + timedelta(days=3), locked=lock), *newcomers], [crew()])
    (kept,) = second.slots_for("m1")
    assert (kept.crew_id, kept.day) == (lock.crew_id, lock.day)
    assert lock.window_start_min <= kept.start_min <= lock.window_end_min
    assert (kept.window_start_min, kept.window_end_min) == (lock.window_start_min, lock.window_end_min)


def test_lock_outside_the_horizon_is_reported_not_moved():
    lock = LockedSlot(crew_id="crew1", day=START + timedelta(days=30), window_start_min=540, window_end_min=720)
    result = plan([job("m1", locked=lock)], [crew()])
    assert result.unschedulable == [{"match_id": "m1", "reason": REASON_LOCK_LOST}]


def test_planning_is_deterministic():
    jobs = [job(f"m{i}", acres=4.0 + i, where=SANGRUR if i % 2 else PATIALA) for i in range(6)]
    crews = [crew("a"), crew("b", depot=PATIALA)]
    assert plan(jobs, crews).assignments == plan(jobs, crews).assignments


def test_helpers():
    assert acres_from_kg(1750) == 1.0
    assert promised_window(9 * 60 + 47, 18 * 60) == (9 * 60, 12 * 60)
    assert promised_window(16 * 60 + 30, 18 * 60) == (16 * 60, 18 * 60)


def test_today_never_offers_a_slot_that_has_already_passed():
    result = plan_pickups([job("m1", acres=3.0, earliest=START, latest=START)], [crew()], START,
                          time_limit_seconds=0, not_before_min_today=14 * 60)
    (a,) = result.assignments
    assert a.start_min >= 14 * 60
    late = plan_pickups([job("m2", earliest=START, latest=START)], [crew()], START,
                        time_limit_seconds=0, not_before_min_today=17 * 60 + 50)
    assert late.assignments == [] and late.unschedulable, "no time left today -> reported, not a past slot"
