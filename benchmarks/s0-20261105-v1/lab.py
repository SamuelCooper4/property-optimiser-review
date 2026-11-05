"""Synthetic S0 numerical/placement experiment, NEVER a production engine.

Omissions: purchase rules, personal quote underwriting, supplemental draws,
overpayments, tax calculations, production admission/authentication and installation.
Money returned as Decimal strings. A single identical file runs in all placements.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Context, Inexact, localcontext
from decimal import Decimal as D
from functools import lru_cache
from typing import Any, cast

VERSION = "s0-lot-segments-experiment-v2"
FIXED = Context(prec=50)
EXACT = Context(prec=4096)
EXACT.traps[Inexact] = True


def add(*values: D) -> D:
    """Bounded exact component addition; refusal on loss of significant digits."""
    with localcontext(EXACT):
        return sum(values, D(0))


def mul(a: D, b: D) -> D:
    """Bounded exact component product, distinct from rounded factor work."""
    with localcontext(EXACT):
        return a * b


def money(value: D) -> str:
    """GBP display only; never used to determine rank or affordability."""
    with localcontext(EXACT) as context:
        context.traps[Inexact] = False
        return format(value.quantize(D(".01"), rounding=ROUND_HALF_UP), "f")


@lru_cache(maxsize=16)
def growth_table(annual: D, months: int) -> tuple[tuple[D, ...], tuple[D, ...]]:
    """Fixed50 age factors and exact prefixes, reusable by every plan."""
    with localcontext(FIXED):
        factors = tuple((1 + annual) ** (D(age) / 12) for age in range(months + 1))
    prefix = [D(0)]
    for factor in factors:
        prefix.append(add(prefix[-1], factor))
    return factors, tuple(prefix)


def segment_value(
    opening: D,
    segments: list[tuple[int, int, D]],
    month: int,
    factors: tuple[D, ...],
    prefix: tuple[D, ...],
) -> D:
    """Exact distributive regrouping of constant month-end contribution lots."""
    values = [mul(opening, factors[month])]
    for start, end, amount in segments:
        last = min(end, month)
        if start <= last:
            factor_sum = add(
                prefix[month - start + 1], prefix[month - last].copy_negate()
            )
            values.append(mul(amount, factor_sum))
    return add(*values)


def default_case() -> dict[str, Any]:
    """Explicit synthetic GBP assumptions; no live market or personal evidence."""
    return {
        "price": "450000",
        "savings": "150000",
        "reserve": "10000",
        "deposit": "112500",
        "monthly": "2000",
        "term_months": 420,
        "horizon_months": 360,
        "view_month": 360,
        "investment_return": ".05",
        "cash_return": "0",
        "upfront_fee": "0",
        "financed_fee": "0",
        "costs": "0",
        "cashback": [],
        "deals": [[420, ".04"]],
    }


def repayment(principal: D, annual: D, months: int) -> D:
    """Fixed50 annuity, with an explicit zero-rate branch."""
    with localcontext(FIXED):
        if not principal:
            return D(0)
        if not annual:
            return principal / D(months)
        rate = annual / 12
        return principal * rate / (1 - (1 + rate) ** (-months))


def project(raw: dict[str, Any], detail: bool = False) -> dict[str, Any]:
    """Evaluate synthetic fixed plans; full payment check, sparse or full views."""
    with localcontext(FIXED):
        return _project(raw, detail)


def _project(raw: dict[str, Any], detail: bool) -> dict[str, Any]:
    c = {**default_case(), **raw}
    n, h = c["term_months"], c["horizon_months"]
    view = c.get("view_month", h)
    if any(type(x) is not int or not 0 <= x <= 720 for x in (n, h, view)) or n < 1:
        return {"status": "unsupported_capability", "model": VERSION}
    if not 1 <= len(c["deals"]) <= 24:
        return {"status": "unsupported_capability", "model": VERSION}
    p, savings, reserve, deposit, funding = (
        D(c[k]) for k in ("price", "savings", "reserve", "deposit", "monthly")
    )
    upfront, financed, costs = (
        D(c[k]) for k in ("upfront_fee", "financed_fee", "costs")
    )
    if not all(
        x.is_finite()
        for x in (p, savings, reserve, deposit, funding, upfront, financed, costs)
    ):
        return {"status": "invalid_input", "model": VERSION}
    if any(
        len(x.as_tuple().digits) > 128 or abs(cast(int, x.as_tuple().exponent)) > 128
        for x in (p, savings, reserve, deposit, funding, upfront, financed, costs)
    ):
        return {"status": "resource_refusal", "model": VERSION}
    cashback = {int(m): D(amount) for m, amount in c["cashback"]}
    opening = add(
        savings,
        cashback.get(0, D(0)),
        reserve.copy_negate(),
        deposit.copy_negate(),
        upfront.copy_negate(),
        costs.copy_negate(),
    )
    if (
        min(opening, reserve, deposit, funding, financed) < 0
        or deposit > p
        or reserve > savings
    ):
        return {"status": "opening_infeasible", "model": VERSION}
    debt = add(p, deposit.copy_negate(), financed)
    extent = max(n, h, view)
    boundaries, elapsed = {}, 0
    for duration, annual in c["deals"]:
        if (
            type(duration) is not int
            or duration < 1
            or not D(annual).is_finite()
            or D(annual) < 0
        ):
            return {"status": "invalid_input", "model": VERSION}
        boundaries[elapsed + 1] = D(annual)
        elapsed += duration
    if elapsed < n:
        return {"status": "unknown_future_assumption", "model": VERSION}
    required, debts, gaps = [D(0)], [debt], []
    contributions: list[tuple[int, int, D]] = []
    rate, payment, first = D(0), D(0), None
    for month in range(1, extent + 1):
        if month in boundaries and month <= n and debt:
            rate = boundaries[month]
            payment = repayment(debt, rate, n - month + 1)
        interest = debt * (rate / 12)
        due = min(payment, add(debt, interest)) if debt else D(0)
        if month >= n:
            due = add(debt, interest)
        if month == 1 and due > funding:
            return {"status": "opening_infeasible", "model": VERSION}
        # Counterfactual contractual schedule continues after failure; no failed wealth.
        debt = add(debt, interest, due.copy_negate())
        resources = add(funding, cashback.get(month, D(0)))
        if due > resources and first is None:
            first = month
        if due > funding:
            gaps.append((month, add(due, funding.copy_negate())))
        if first is None:
            amount = add(resources, due.copy_negate())
            if contributions and contributions[-1][2] == amount:
                start, _, q = contributions[-1]
                contributions[-1] = (start, month, q)
            else:
                contributions.append((month, month, amount))
        required.append(due)
        debts.append(debt)
    factors, prefix = growth_table(D(c["investment_return"]), extent)
    cash_factors, _ = growth_table(D(c["cash_return"]), extent)

    def row(month: int) -> dict[str, Any]:
        valid = first is None or month < first
        investment = (
            segment_value(opening, contributions, month, factors, prefix)
            if valid
            else None
        )
        cash = mul(reserve, cash_factors[month]) if valid else None
        position = (
            add(cast(D, cash), cast(D, investment), debts[month].copy_negate())
            if valid
            else None
        )
        return {
            "month": month,
            "debt": str(debts[month]),
            "cash": None if cash is None else str(cash),
            "investment": None if investment is None else str(investment),
            "position": None if position is None else str(position),
            "required": str(required[month]),
            "funded": valid,
        }

    target, viewed = row(h), row(view)
    result = {
        "status": "ok",
        "model": VERSION,
        "deposit": str(deposit),
        "term_months": n,
        "horizon_months": h,
        "view_month": view,
        "position": target["position"],
        "target": target,
        "view": viewed,
        "rank_eligible": first is None,
        "first_gap_month": first,
        "first_required": str(required[first]) if first else None,
        "gap_month_count": len(gaps),
        "peak_gap": str(max((x[1] for x in gaps), default=D(0))),
        "opening_investment": str(opening),
        "opening_debt": str(debts[0]),
        "initial_payment": str(required[1]),
        "segment_count": len(contributions),
    }
    if detail:
        result["rows"] = [row(month) for month in range(extent + 1)]
        result["required"] = [str(x) for x in required]
    return result


def summarise_search(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank the evaluated synthetic plans; shared by serial and resumable experiments."""
    ranked = [
        r for r in results if r.get("rank_eligible") and r.get("position") is not None
    ]
    best = max((D(r["position"]) for r in ranked), default=None)
    return {
        "status": "ok",
        "model": VERSION,
        "claim": "best_evaluated",
        "evaluated": len(results),
        "best": [r for r in ranked if D(r["position"]) == best],
        "points": [
            {
                k: r.get(k)
                for k in (
                    "status",
                    "deposit",
                    "term_months",
                    "position",
                    "rank_eligible",
                    "first_gap_month",
                )
            }
            for r in results
        ],
    }


def respond(request: dict[str, Any]) -> dict[str, Any]:
    """Bounded experiment protocol shared by CPython, browser and hybrid tests."""
    operation = request.get("operation", "select")
    case = {**default_case(), **request.get("case", {})}
    if operation in ("select", "scrub"):
        return project(case, request.get("detail", False))
    if operation in ("search", "scenario", "horizon"):
        choices = request.get(
            "choices",
            [[str(90000 + i * 2500), n * 12] for n in (25, 30, 35) for i in range(21)],
        )
        if len(choices) > 2048:
            return {"status": "resource_refusal", "model": VERSION}
        results = [
            project(
                {
                    **case,
                    "deposit": d,
                    "term_months": n,
                    "deals": request.get("deals", [[n, ".04"]]),
                }
            )
            for d, n in choices
        ]
        return summarise_search(results)
    if operation == "compare":
        inputs = [{**default_case(), **c} for c in request["plans"]]
        if len(inputs) != 2:
            return {"status": "incomparable", "difference": None, "model": VERSION}
        common = (
            "price",
            "savings",
            "reserve",
            "monthly",
            "investment_return",
            "cash_return",
            "costs",
        )
        if inputs[0]["horizon_months"] != inputs[1]["horizon_months"] or any(
            D(inputs[0][key]) != D(inputs[1][key]) for key in common
        ):
            return {"status": "incomparable", "difference": None, "model": VERSION}
        plans = [project(c) for c in inputs]
        both = all(p.get("position") is not None for p in plans)
        horizon = inputs[0]["horizon_months"]
        return {
            "status": "ok",
            "model": VERSION,
            "plans": plans,
            "comparison_month": horizon,
            "both_funded_at_month": both,
            "rank_eligible_pair": all(p.get("rank_eligible") for p in plans),
            "later_failure_months": [
                p["first_gap_month"]
                if p.get("first_gap_month") is not None
                and p["first_gap_month"] > horizon
                else None
                for p in plans
            ],
            "difference": str(
                add(D(plans[0]["position"]), D(plans[1]["position"]).copy_negate())
            )
            if both
            else None,
        }
    if operation == "analysis":
        return {
            "status": "ok",
            "cases": [
                project({**case, "investment_return": r}, True)
                for r in ("0", ".03", ".05", ".08")
            ],
        }
    return {"status": "unsupported_operation", "model": VERSION}


def respond_json(raw: str) -> str:
    """JSON-string bridge without binary floating point for financial fields."""
    return json.dumps(respond(json.loads(raw)), separators=(",", ":"))
