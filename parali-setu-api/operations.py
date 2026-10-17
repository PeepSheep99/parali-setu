"""Runs the business planners on live data and saves what the apps read.

- run_procurement: real district straw (APY crop statistics) x this season's
  remaining harvest timing (TimesFM forecast from FIRMS) x the share we
  expect farmers to book -> procurement LP -> today's posted price per
  district, the district -> depot routing, and the weekly buying plan.
- run_deliveries: depot stock and planned intake -> delivery LP against
  signed customer orders -> monthly shipments and any shortfall.
- quote_order: a customer's delivered price, built up from costs.

Assumptions are module constants, returned with every plan so the ops
console can show them next to the numbers they produce.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import firestore_store as store
import pickups
from costs import (
    FARM_GATE_BASE_PER_KG,
    IN_SEASON_DELIVERED_PER_T_INR,
    clamp_farm_gate,
    quote,
    road_km,
)
from deliveries import DepotStock, OrderLine, plan_deliveries
from forecast.demand_segments import segment_totals
from geo import DISTRICT_COORDS
from procurement import Depot, DistrictSupply, SalesBook, plan_procurement
from scheduler import STRAW_T_PER_ACRE

RICE_CSV = Path(__file__).resolve().parent / "forecast" / "data" / "rice_production.csv"
# ASSUMPTION: share of a district's paddy straw we expect farmers to book
# with us this season: a first-season pilot in eight districts. 0.5% is about
# a thousand acres a day at the peak, which our crews plus on-call crews can
# reach; 3% would be several thousand acres a day, about 300 crews.
BOOKING_SHARE = 0.005
# ASSUMPTION: share of Punjab's published industrial straw demand we could
# sell beyond signed orders, and the discount on such spot sales.
FORECAST_MARKET_SHARE = 0.005
SPOT_DISCOUNT = 0.9
WORK_DAYS_PER_WEEK = 6
DELIVERY_MONTHS = 12
COLLECTION_PEAK = (11, 10)   # month, day: straw is mostly collected by mid-November


@lru_cache(maxsize=1)
def district_straw_t() -> dict[str, dict]:
    """Latest year's paddy straw per operating district from the APY data."""
    latest: dict[str, dict] = {}
    with RICE_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row["district"]
            if name in DISTRICT_COORDS and int(row["year"]) >= int(latest.get(name, {}).get("year", 0)):
                latest[name] = {"year": int(row["year"]), "straw_t": float(row["straw_t"]), "rice_t": float(row["rice_t"])}
    return latest


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def season_timing(forecast: dict | None, district: str, weeks: list[date]) -> tuple[list[float], float]:
    """(share of the remaining season's straw in each week, fraction of the
    season still to come) for one district, from the TimesFM forecast and
    this season's observed fires. Without a forecast the remaining weeks are
    weighted evenly and half the season is assumed to remain."""
    if not forecast or district not in forecast.get("districts", {}):
        return [1 / len(weeks)] * len(weeks), 0.5
    by_week = {w["week"]: max(0.0, w["fire_pixels"]) for w in forecast["districts"][district]}
    values = [by_week.get(w.isoformat(), 0.0) for w in weeks]
    ahead = sum(values)
    if ahead <= 0:
        return [1 / len(weeks)] * len(weeks), 0.5
    observed = forecast.get("observed_to_date", {}).get(district, 0.0)
    return [v / ahead for v in values], ahead / (ahead + observed)


def depot_capacity_t_per_week(crews: list[dict], partner: bool) -> float:
    return sum(c.get("acres_per_day", 20.0) * STRAW_T_PER_ACRE * WORK_DAYS_PER_WEEK
               for c in crews if bool(c.get("partner")) == partner)


ONCALL_ACRES_PER_DAY = 20.0


def readiness(db, today: date | None = None, days: int = 14) -> list[dict]:
    """For each of the next `days` days and each depot: the farm acres the
    forecast expects farmers to book with us (TimesFM timing x district straw x
    our booking share, as in run_procurement, spread over working days),
    against what our own crews clear in a day; the on-call crews that gap
    needs from the depot's pool; and any acres beyond even the pool, which is
    the signal to sign up more crews before the peak."""
    today = today or pickups.now_ist().date()
    plan = store.get_plan(db, "procurement_current") or {}
    shares = plan.get("district_depot_share", {})
    by_week: dict[str, dict[str, float]] = {}
    for row in plan.get("weekly", []):
        share = shares.get(row["district"], {})
        total = sum(share.values())
        if not total or not row.get("bookable_t"):
            continue
        week = by_week.setdefault(row["week"], {})
        for depot_id, s in share.items():
            week[depot_id] = week.get(depot_id, 0.0) + row["bookable_t"] * s / total
    out = []
    for depot in store.get_depots(db):
        crews = store.get_crews_for_depot(db, depot["id"])
        own = sum(c.get("acres_per_day", 20.0) for c in crews if not c.get("partner"))
        pool = len([c for c in crews if c.get("partner")])
        for i in range(days):
            day = today + timedelta(days=i)
            tonnes = by_week.get(_monday(day).isoformat(), {}).get(depot["id"], 0.0)
            acres = round(tonnes / WORK_DAYS_PER_WEEK / STRAW_T_PER_ACRE, 1)
            gap = max(0.0, acres - own)
            needed = int(-(-gap // ONCALL_ACRES_PER_DAY))
            out.append({"date": day.isoformat(), "depot_id": depot["id"], "depot_name": depot["name"],
                        "forecast_acres": acres, "own_capacity_acres": own,
                        "oncall_crews_needed": min(needed, pool), "oncall_pool": pool,
                        "beyond_pool_acres": round(max(0.0, gap - pool * ONCALL_ACRES_PER_DAY), 1),
                        "crews_to_sign_up": max(0, needed - pool)})
    return out


def active_orders(orders: list[dict]) -> list[dict]:
    return [o for o in orders if o.get("status") != "cancelled"]


def order_code(order_id: str) -> str:
    """A short reference a customer can quote, e.g. PO-4F2KQ."""
    return "PO-" + "".join(ch for ch in order_id if ch.isalnum())[-5:].upper()


def _orders_tonnes_and_price(orders: list[dict], months: int, start: date) -> tuple[float, float]:
    total = value = 0.0
    for o in active_orders(orders):
        for month, tonnes in (o.get("tonnes_by_month") or {}).items():
            m = date.fromisoformat(month)
            if start <= m < add_months(start, months):
                total += tonnes
                value += tonnes * o.get("quote", {}).get("price_per_t", IN_SEASON_DELIVERED_PER_T_INR)
    return total, (value / total if total else 0.0)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def run_procurement(db, today: date | None = None, repost_today: bool = False,
                    extra_order: tuple[float, float] | None = None, dry_run: bool = False) -> dict:
    """Plans procurement. A price already posted for today is never changed
    mid-day (farmers were seeing 0.60 then 0.74 within minutes); a re-plan
    only fills in missing districts unless repost_today is set (demo reset).
    `extra_order` = (tonnes, price per tonne) adds a candidate order to the book;
    with dry_run nothing is saved and only the plan's totals come back."""
    today = today or pickups.now_ist().date()
    forecast = store.get_forecast(db, f"supply_live_{today.year}")
    weeks = sorted({date.fromisoformat(w["week"]) for ws in (forecast or {}).get("districts", {}).values() for w in ws})
    weeks = [w for w in weeks if w >= _monday(today)] or [_monday(today) + timedelta(weeks=i) for i in range(6)]
    straw = district_straw_t()

    supply, timing_notes = [], {}
    for district, (lat, lon) in DISTRICT_COORDS.items():
        if district not in straw:
            continue
        shares, remaining = season_timing(forecast, district, weeks)
        bookable = straw[district]["straw_t"] * BOOKING_SHARE * remaining
        supply.append(DistrictSupply(district, lat, lon, tuple(round(bookable * s, 1) for s in shares)))
        timing_notes[district] = {"straw_t": straw[district]["straw_t"], "data_year": straw[district]["year"],
                                  "season_remaining": round(remaining, 3), "bookable_t": round(bookable, 1)}

    depots_docs = store.get_depots(db)
    depots = []
    for d in depots_docs:
        crews = store.get_crews_for_depot(db, d["id"])
        depots.append(Depot(d["id"], d["name"], d["lat"], d["lon"], d["capacity_t"],
                            depot_capacity_t_per_week(crews, partner=False),
                            depot_capacity_t_per_week(crews, partner=True), d.get("radius_km", 80)))

    month0 = date(today.year, today.month, 1)
    committed_t, committed_price = _orders_tonnes_and_price(store.get_orders(db), DELIVERY_MONTHS, month0)
    low, _ = segment_totals()
    if extra_order:
        value = committed_t * committed_price + extra_order[0] * extra_order[1]
        committed_t += extra_order[0]
        committed_price = value / committed_t
    sales = SalesBook(committed_t=committed_t, committed_price_per_t=committed_price,
                      forecast_t=low * FORECAST_MARKET_SHARE,
                      forecast_price_per_t=(committed_price or IN_SEASON_DELIVERED_PER_T_INR) * SPOT_DISCOUNT)
    plan = plan_procurement(supply, depots, sales)
    if plan.status != "optimal":
        return {"status": plan.status}

    if dry_run:
        return {"status": plan.status, "committed_t": round(committed_t, 1), "shortfall_t": plan.shortfall_t}

    week_index = max(0, min(len(weeks) - 1, next((i for i, w in enumerate(weeks) if w <= today < w + timedelta(weeks=1)), 0)))
    rows = []
    for s in supply:
        shadow = plan.shadow_price_per_t.get((s.district, week_index), 0.0)
        price = plan.posted_price_per_kg.get((s.district, week_index), clamp_farm_gate(FARM_GATE_BASE_PER_KG))
        premium = round(price - FARM_GATE_BASE_PER_KG, 2)
        if premium > 0:
            reason = (f"Our orders need more straw from {s.district} this week than we expect farmers to book, "
                      f"so the price is up by {premium} rupees per kg.")
            code = "scarce"
        else:
            reason = f"We expect enough straw from {s.district} this week, so the base price of {FARM_GATE_BASE_PER_KG} rupees per kg applies."
            code = "base"
        rows.append({"date": today.isoformat(), "district": s.district, "price_per_kg": price,
                     "shadow_price_per_t": shadow, "reason": reason, "reason_code": code})
    if not repost_today:
        posted = {r["district"] for r in store.get_posted_prices_for_day(db, today.isoformat())}
        rows = [r for r in rows if r["district"] not in posted]
    store.save_posted_prices(db, rows)

    weekly = []
    for i, w in enumerate(weeks):
        for s in supply:
            weekly.append({
                "week": w.isoformat(), "district": s.district,
                "bookable_t": s.available_t_by_week[i] if i < len(s.available_t_by_week) else 0.0,
                "planned_t": round(sum(t for (d, _, ww), t in plan.buy.items() if d == s.district and ww == i), 1),
                "price_per_kg": plan.posted_price_per_kg.get((s.district, i)),
            })
    shares = {s.district: plan.district_depot_share(s.district) for s in supply}
    own = sum(plan.own_t.values())
    partner = sum(plan.partner_t.values())
    summary = {
        "status": plan.status, "date": today.isoformat(), "weeks": [w.isoformat() for w in weeks],
        "margin_inr": plan.margin_inr, "sell_committed_t": plan.sell_committed_t,
        "sell_forecast_t": plan.sell_forecast_t, "shortfall_t": plan.shortfall_t,
        "committed_t": round(committed_t, 1), "committed_price_per_t": round(committed_price, 2),
        "partner_share": round(partner / (own + partner), 3) if own + partner else 0.0,
        "district_depot_share": shares, "weekly": weekly, "districts": timing_notes,
        "depot_intake": {p.id: {"own_t": round(sum(t for (pid, _), t in plan.own_t.items() if pid == p.id), 1),
                                "partner_t": round(sum(t for (pid, _), t in plan.partner_t.items() if pid == p.id), 1)}
                         for p in depots},
        "assumptions": {"booking_share": BOOKING_SHARE, "forecast_market_share": FORECAST_MARKET_SHARE,
                        "spot_discount": SPOT_DISCOUNT, "forecast": "TimesFM via BigQuery AI.FORECAST" if forecast else "none (even weeks)"},
    }
    store.save_plan(db, "procurement_current", summary)
    return summary


def depot_stock_t(db, depot_id: str) -> float:
    moves = store.get_inventory_moves(db, depot_id)
    return round(sum(m["tonnes"] if m["kind"] == "inbound" else -m["tonnes"] for m in moves), 3)


def _delivery_inputs(db, today: date):
    """Depot stock and active orders as the delivery LP sees them. Orders are
    ranked by when they were signed (earliest first)."""
    month0 = date(today.year, today.month, 1)
    months = [add_months(month0, i) for i in range(DELIVERY_MONTHS)]
    procurement = store.get_plan(db, "procurement_current") or {}

    depots = []
    for d in store.get_depots(db):
        inbound = [0.0] * DELIVERY_MONTHS
        for row in procurement.get("weekly", []):
            share = procurement.get("district_depot_share", {}).get(row["district"], {})
            total = sum(share.values())
            if not total or not row["planned_t"]:
                continue
            w = date.fromisoformat(row["week"])
            idx = (w.year - month0.year) * 12 + w.month - month0.month
            if 0 <= idx < DELIVERY_MONTHS:
                inbound[idx] += row["planned_t"] * share.get(d["id"], 0.0) / total
        depots.append(DepotStock(d["id"], d["lat"], d["lon"], d["capacity_t"], max(0.0, depot_stock_t(db, d["id"])),
                                 tuple(round(x, 2) for x in inbound)))

    customers = {c["id"]: c for c in store.get_customers(db)}
    docs = active_orders(store.get_orders(db))
    lines = []
    for rank, o in enumerate(docs):
        site = o.get("site") or customers.get(o["customer_id"], {})
        by_month = o.get("tonnes_by_month") or {}
        lines.append(OrderLine(o["id"], o["customer_id"], site["lat"], site["lon"],
                               tuple(float(by_month.get(m.isoformat(), 0.0)) for m in months), rank))
    return depots, lines, months


def run_deliveries(db, today: date | None = None) -> dict:
    today = today or pickups.now_ist().date()
    depots, lines, months = _delivery_inputs(db, today)
    plan = plan_deliveries(depots, lines, DELIVERY_MONTHS)
    rows = [{"id": f"del_{oid}_{pid}_{m}", "order_id": oid, "depot_id": pid, "month": months[m].isoformat(),
             "tonnes": t, "customer_id": next((l.customer_id for l in lines if l.id == oid), None)}
            for (pid, oid, m), t in plan.shipments.items()]
    store.replace_deliveries(db, rows)
    summary = {"status": plan.status, "months": [m.isoformat() for m in months],
               "shortfall_t": plan.total_shortfall_t,
               "shortfall": [{"order_id": o, "month": months[m].isoformat(), "tonnes": t} for (o, m), t in plan.shortfall.items()],
               "haul_cost_inr": plan.haul_cost_inr, "storage_cost_inr": plan.storage_cost_inr,
               "stock": {f"{p}|{months[m].isoformat()}": t for (p, m), t in plan.stock.items()}}
    store.save_plan(db, "deliveries_current", summary)
    return summary


def committable(db, site: tuple[float, float], by_month: dict[str, float], price_per_t: float,
                today: date | None = None) -> dict:
    """How much of a candidate order we could supply if it were signed now.
    The procurement plan is re-run with the order on the book; whatever it
    cannot source on top of today's shortfall is what we cannot commit. Signed
    orders are served first (see deliveries.PRIORITY_STEP_PER_T), so a new
    order never shortens one of them. The monthly split is proportional.
    Saves nothing."""
    today = today or pickups.now_ist().date()
    asked = round(sum(by_month.values()), 2)
    base = run_procurement(db, today, dry_run=True)
    trial = run_procurement(db, today, extra_order=(asked, price_per_t), dry_run=True)
    if trial.get("status") != "optimal" or base.get("status") != "optimal":
        return {"asked_t": asked, "committable_t": 0.0, "shortfall_t": asked, "can_fill": False,
                "by_month": {m: 0.0 for m in by_month}, "max_t_per_month": 0.0}
    extra_short = max(0.0, trial["shortfall_t"] - base["shortfall_t"])
    ok = round(max(0.0, asked - extra_short), 2)
    ratio = ok / asked if asked else 0.0
    per_month = {m: round(t * ratio, 2) for m, t in by_month.items()}
    return {"asked_t": asked, "committable_t": ok, "shortfall_t": round(asked - ok, 2), "can_fill": asked - ok < 0.5,
            "by_month": per_month, "max_t_per_month": round(min(per_month.values()), 1) if per_month else 0.0}


def months_in_storage(start_month: date, months: int) -> float:
    """Average months each delivery sits in store: from the most recent
    collection peak (mid-November) to the middle of the delivery month,
    at least half a month."""
    gaps = []
    for i in range(months):
        m = add_months(start_month, i)
        peak = date(m.year if m.month >= COLLECTION_PEAK[0] else m.year - 1, *COLLECTION_PEAK)
        gaps.append(max(0.5, ((m - peak).days + 15) / 30.4))
    return round(sum(gaps) / len(gaps), 2)


def quote_order(db, site: tuple[float, float], start_month: date, months: int, margin_pct: float | None = None,
                today: date | None = None) -> dict:
    today = today or pickups.now_ist().date()
    depots = store.get_depots(db)
    if not depots:
        raise ValueError("no depots configured")
    depot = min(depots, key=lambda d: road_km(site[0], site[1], d["lat"], d["lon"]))
    prices = [p["price_per_kg"] for p in store.get_posted_prices_for_day(db, today.isoformat())]
    farm_gate = sum(prices) / len(prices) if prices else FARM_GATE_BASE_PER_KG
    plan = store.get_plan(db, "procurement_current") or {}
    kwargs = {} if margin_pct is None else {"margin_pct": margin_pct}
    q = quote(round(farm_gate, 3), plan.get("partner_share", 0.0), months_in_storage(start_month, months),
              (depot["lat"], depot["lon"]), site, **kwargs)
    return {**q.as_dict(), "depot_id": depot["id"], "depot_name": depot["name"],
            "road_km": round(road_km(site[0], site[1], depot["lat"], depot["lon"]), 1)}


def book_listing(db, listing: dict, today: date | None = None) -> tuple[dict | None, dict | None]:
    """Prices a confirmed listing at today's posted price for its district,
    picks the depot the procurement plan intends for that district (or the
    nearest that can reach the farm), and saves an `offered` booking.
    Returns (booking, price); booking is None when no depot reaches the farm.
    The caller plans the depot so the booking gets its slot."""
    today = today or pickups.now_ist().date()
    location = pickups.listing_location(listing)
    district = pickups.listing_district(listing)
    if location is None or district is None:
        return None, None
    price = store.get_posted_price(db, today.isoformat(), district)
    if price is None:
        run_procurement(db, today)
        price = store.get_posted_price(db, today.isoformat(), district)
    plan = store.get_plan(db, "procurement_current") or {}
    depot = pickups.choose_depot(store.get_depots(db), plan.get("district_depot_share", {}).get(district, {}),
                                 location[0], location[1])
    if depot is None or price is None:
        return None, price
    booking = store.save_booking(db, {
        "listing_id": listing["id"], "farmer_id": listing["farmer_id"], "depot_id": depot["id"], "district": district,
        "kg": listing["quantity_kg"], "acres": listing.get("acres"), "price_per_kg": price["price_per_kg"],
        "price_reason_code": price.get("reason_code"), "contact": listing.get("contact"),
        "village": listing.get("village_or_district"), "sowing_deadline": listing.get("sowing_deadline"),
        "location_approximate": location[2], "created_at": pickups.now_ist().isoformat(),
    })
    return booking, price
