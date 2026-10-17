"""Delivery planner: which depot ships how much to which customer order each
month. OR-Tools linear program (GLOP) with inventory carried month to month.

Straw arrives in a burst (Oct-Nov) and is consumed all year, so this is a
storage problem as much as a transport one. For every depot and month:

    stock[p, m] = stock[p, m-1] + inbound[p, m] - shipped from p in month m
    0 <= stock[p, m] <= capacity[p]

Each order-month is met from any depot or recorded as a shortfall; the
objective minimises haulage + storage + a heavy shortfall penalty, so a
shortfall appears only when there is genuinely not enough straw. A shortfall
is reported, never hidden: it is the signal to buy more next season or to
book partner supply.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from costs import STORAGE_PER_T_MONTH_INR, haul_per_t

SHORTFALL_PENALTY_PER_T = 50_000.0


@dataclass(frozen=True)
class DepotStock:
    id: str
    lat: float
    lon: float
    capacity_t: float
    opening_t: float
    inbound_t_by_month: tuple[float, ...]   # straw arriving each month


@dataclass(frozen=True)
class OrderLine:
    id: str
    customer_id: str
    lat: float
    lon: float
    tonnes_by_month: tuple[float, ...]


@dataclass
class DeliveryPlan:
    status: str
    shipments: dict[tuple[str, str, int], float] = field(default_factory=dict)   # (depot, order, month) -> t
    stock: dict[tuple[str, int], float] = field(default_factory=dict)
    shortfall: dict[tuple[str, int], float] = field(default_factory=dict)
    haul_cost_inr: float = 0.0
    storage_cost_inr: float = 0.0

    @property
    def total_shortfall_t(self) -> float:
        return round(sum(self.shortfall.values()), 2)


def plan_deliveries(depots: list[DepotStock], orders: list[OrderLine], months: int) -> DeliveryPlan:
    solver = pywraplp.Solver.CreateSolver("GLOP")
    inf = solver.infinity()
    ship = {(p.id, o.id, m): solver.NumVar(0, inf, f"ship_{p.id}_{o.id}_{m}")
            for p in depots for o in orders for m in range(months)}
    stock = {(p.id, m): solver.NumVar(0, p.capacity_t, f"stock_{p.id}_{m}") for p in depots for m in range(months)}
    short = {(o.id, m): solver.NumVar(0, inf, f"short_{o.id}_{m}") for o in orders for m in range(months)}

    for p in depots:
        for m in range(months):
            inbound = p.inbound_t_by_month[m] if m < len(p.inbound_t_by_month) else 0.0
            row = solver.Constraint(inbound + (p.opening_t if m == 0 else 0.0),
                                    inbound + (p.opening_t if m == 0 else 0.0), f"stock_{p.id}_{m}")
            row.SetCoefficient(stock[(p.id, m)], 1)
            if m > 0:
                row.SetCoefficient(stock[(p.id, m - 1)], -1)
            for o in orders:
                row.SetCoefficient(ship[(p.id, o.id, m)], 1)
    for o in orders:
        for m in range(months):
            need = o.tonnes_by_month[m] if m < len(o.tonnes_by_month) else 0.0
            row = solver.Constraint(need, need, f"order_{o.id}_{m}")
            for p in depots:
                row.SetCoefficient(ship[(p.id, o.id, m)], 1)
            row.SetCoefficient(short[(o.id, m)], 1)

    haul = {(p.id, o.id): haul_per_t(p.lat, p.lon, o.lat, o.lon) for p in depots for o in orders}
    obj = solver.Objective()
    for (pid, oid, _), var in ship.items():
        obj.SetCoefficient(var, haul[(pid, oid)])
    for var in stock.values():
        obj.SetCoefficient(var, STORAGE_PER_T_MONTH_INR)
    for var in short.values():
        obj.SetCoefficient(var, SHORTFALL_PENALTY_PER_T)
    obj.SetMinimization()

    if solver.Solve() != pywraplp.Solver.OPTIMAL:
        return DeliveryPlan(status="infeasible")
    shipments = {k: round(v.solution_value(), 2) for k, v in ship.items() if v.solution_value() > 1e-6}
    return DeliveryPlan(
        status="optimal",
        shipments=shipments,
        stock={k: round(v.solution_value(), 2) for k, v in stock.items()},
        shortfall={k: round(v.solution_value(), 2) for k, v in short.items() if v.solution_value() > 1e-6},
        haul_cost_inr=round(sum(t * haul[(p, o)] for (p, o, _), t in shipments.items()), 2),
        storage_cost_inr=round(sum(v.solution_value() for v in stock.values()) * STORAGE_PER_T_MONTH_INR, 2),
    )
