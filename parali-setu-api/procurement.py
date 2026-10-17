"""Procurement planner: how much straw to buy in each district, which depot
it goes to, and the farm-gate price to post. OR-Tools linear program (GLOP).

Decision variables (tonnes, over the planning weeks):
- buy[d, p, w]   straw bought in district d, taken to depot p, in week w
- own[p, w], partner[p, w]   how much of depot p's intake our own crews and
  hired partner crews collect
- sell_committed, sell_forecast   straw sold against signed forward orders
  and against forecast demand

Constraints
- what farmers in a district make available that week (forecast straw x the
  share we expect to book) caps buy[d, ., w]
- a depot only takes districts within its collection radius and up to its
  storage capacity over the season
- crew capacity per depot per week (own), plus partner capacity
- everything bought is sold: committed orders first (a shortfall is allowed
  but heavily penalised), then forecast demand up to its cap

Objective: maximise margin = sales - farm-gate - haul to depot - collection -
storage - shortfall penalty.

Posted price. The dual value (shadow price) of a district-week's supply
constraint is what one more tonne from there would add to margin. When it is
positive, we want more straw from that district than farmers are expected to
book, so the posted price rises by a share of it; when it is zero the base
price stands. This is a deterministic optimizer output, explainable in one
sentence, and Gemini never sets it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from costs import (
    FARM_GATE_BASE_PER_KG,
    OWN_COLLECTION_PER_T_INR,
    PARTNER_COLLECTION_PER_T_INR,
    SHADOW_PRICE_SHARE,
    STORAGE_PER_T_MONTH_INR,
    clamp_farm_gate,
    haul_per_t,
    road_km,
)

SHORTFALL_PENALTY_PER_T = 50_000.0   # far above any margin: commitments come first
DEFAULT_RADIUS_KM = 80.0


@dataclass(frozen=True)
class DistrictSupply:
    district: str
    lat: float
    lon: float
    available_t_by_week: tuple[float, ...]   # expected bookable straw per week


@dataclass(frozen=True)
class Depot:
    id: str
    name: str
    lat: float
    lon: float
    capacity_t: float
    own_t_per_week: float
    partner_t_per_week: float
    radius_km: float = DEFAULT_RADIUS_KM


@dataclass(frozen=True)
class SalesBook:
    committed_t: float                 # signed forward orders
    committed_price_per_t: float
    forecast_t: float                  # further demand we expect to sell
    forecast_price_per_t: float
    months_in_storage: float = 5.5     # straw is sold evenly over the year


@dataclass
class ProcurementPlan:
    status: str
    buy: dict[tuple[str, str, int], float] = field(default_factory=dict)
    own_t: dict[tuple[str, int], float] = field(default_factory=dict)
    partner_t: dict[tuple[str, int], float] = field(default_factory=dict)
    sell_committed_t: float = 0.0
    sell_forecast_t: float = 0.0
    shortfall_t: float = 0.0
    margin_inr: float = 0.0
    shadow_price_per_t: dict[tuple[str, int], float] = field(default_factory=dict)
    posted_price_per_kg: dict[tuple[str, int], float] = field(default_factory=dict)

    def district_depot_share(self, district: str) -> dict[str, float]:
        """Planned tonnes from a district by depot, used to route a new
        booking from that district to the depot the plan intends."""
        out: dict[str, float] = {}
        for (d, p, _), t in self.buy.items():
            if d == district and t > 1e-6:
                out[p] = out.get(p, 0.0) + t
        return out


def posted_price(shadow_price_per_t: float) -> float:
    """Base price plus a share of the shadow price, in Rs/kg, within bounds."""
    return clamp_farm_gate(FARM_GATE_BASE_PER_KG + SHADOW_PRICE_SHARE * max(0.0, shadow_price_per_t) / 1000)


def plan_procurement(supply: list[DistrictSupply], depots: list[Depot], sales: SalesBook) -> ProcurementPlan:
    weeks = max((len(s.available_t_by_week) for s in supply), default=0)
    solver = pywraplp.Solver.CreateSolver("GLOP")
    inf = solver.infinity()
    farm_gate_per_t = FARM_GATE_BASE_PER_KG * 1000
    storage_per_t = sales.months_in_storage * STORAGE_PER_T_MONTH_INR

    # Haul cost (Rs/t) for every district-depot pair within the depot's radius.
    reach = {(s.district, p.id): haul_per_t(s.lat, s.lon, p.lat, p.lon)
             for s in supply for p in depots if road_km(s.lat, s.lon, p.lat, p.lon) <= p.radius_km}

    buy = {(d, p, w): solver.NumVar(0, inf, f"buy_{d}_{p}_{w}") for (d, p) in reach for w in range(weeks)}
    own = {(p.id, w): solver.NumVar(0, p.own_t_per_week, f"own_{p.id}_{w}") for p in depots for w in range(weeks)}
    partner = {(p.id, w): solver.NumVar(0, p.partner_t_per_week, f"partner_{p.id}_{w}") for p in depots for w in range(weeks)}
    sell_c = solver.NumVar(0, sales.committed_t, "sell_committed")
    sell_f = solver.NumVar(0, sales.forecast_t, "sell_forecast")
    short = solver.NumVar(0, inf, "shortfall")

    supply_rows = {}
    for s in supply:
        for w in range(weeks):
            avail = s.available_t_by_week[w] if w < len(s.available_t_by_week) else 0.0
            row = solver.Constraint(0, avail, f"supply_{s.district}_{w}")
            for p in depots:
                if (s.district, p.id, w) in buy:
                    row.SetCoefficient(buy[(s.district, p.id, w)], 1)
            supply_rows[(s.district, w)] = row
    for p in depots:
        cap = solver.Constraint(0, p.capacity_t, f"capacity_{p.id}")
        for (d, pid, w), var in buy.items():
            if pid == p.id:
                cap.SetCoefficient(var, 1)
        for w in range(weeks):
            crew = solver.Constraint(0, 0, f"crews_{p.id}_{w}")   # intake == own + partner
            for (d, pid, ww), var in buy.items():
                if pid == p.id and ww == w:
                    crew.SetCoefficient(var, 1)
            crew.SetCoefficient(own[(p.id, w)], -1)
            crew.SetCoefficient(partner[(p.id, w)], -1)
    balance = solver.Constraint(0, 0, "sold_equals_bought")
    for var in buy.values():
        balance.SetCoefficient(var, 1)
    balance.SetCoefficient(sell_c, -1)
    balance.SetCoefficient(sell_f, -1)
    commit = solver.Constraint(sales.committed_t, sales.committed_t, "committed_orders")
    commit.SetCoefficient(sell_c, 1)
    commit.SetCoefficient(short, 1)

    obj = solver.Objective()
    obj.SetCoefficient(sell_c, sales.committed_price_per_t)
    obj.SetCoefficient(sell_f, sales.forecast_price_per_t)
    obj.SetCoefficient(short, -SHORTFALL_PENALTY_PER_T)
    for (d, p, w), var in buy.items():
        obj.SetCoefficient(var, -(farm_gate_per_t + reach[(d, p)] + storage_per_t))
    for var in own.values():
        obj.SetCoefficient(var, -OWN_COLLECTION_PER_T_INR)
    for var in partner.values():
        obj.SetCoefficient(var, -PARTNER_COLLECTION_PER_T_INR)
    obj.SetMaximization()

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        return ProcurementPlan(status="infeasible")
    plan = ProcurementPlan(
        status="optimal",
        buy={k: round(v.solution_value(), 2) for k, v in buy.items() if v.solution_value() > 1e-6},
        own_t={k: round(v.solution_value(), 2) for k, v in own.items()},
        partner_t={k: round(v.solution_value(), 2) for k, v in partner.items()},
        sell_committed_t=round(sell_c.solution_value(), 2),
        sell_forecast_t=round(sell_f.solution_value(), 2),
        shortfall_t=round(short.solution_value(), 2),
        # The shortfall penalty steers the solver; it is not money anyone pays.
        margin_inr=round(obj.Value() + SHORTFALL_PENALTY_PER_T * short.solution_value(), 2),
    )
    for key, row in supply_rows.items():
        shadow = max(0.0, row.dual_value())
        plan.shadow_price_per_t[key] = round(shadow, 2)
        plan.posted_price_per_kg[key] = posted_price(shadow)
    return plan
