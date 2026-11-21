"""Synthetic phone reports for borrowing costs, owned assets and return sensitivity."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D, localcontext
from functools import lru_cache

import model as m
import phone_provider as phone
from target_reporting import composition


VERSION = 'phone-ownership-2026-11-21-v1'
# Display domain for the synthetic tester. A household's entered rate always fits.
GROWTH_LOW = D('-.04')
GROWTH_HIGH = D('.12')
GROWTH_INTERVALS = 16
# A verified sign-changing bracket narrower than 0.001 percentage points.
CROSSING_WIDTH = D('.00001')


@lru_cache(maxsize=8)
def _ledger(i: m.Inputs, term: int, deposit: D, month: int) -> dict:
    return m.project(i, deposit.quantize(m.PENNY), term, objective_month=month, through_month=month)


def _ownership(i: m.Inputs, term: int, deposit: D, month: int, page: int) -> dict:
    plan = _ledger(i, term, deposit, month)
    rows = plan['rows']
    opening, closing = rows[0], rows[-1]
    principal = opening['debt'] - closing['debt']
    financed_fee = plan['product_fee'] if plan['fee_mode'] == 'loan' else m.ZERO
    result = dict(interest=closing['interest_total'], principal=principal, still_owed=closing['debt'],
                  overpaid=sum(r['overpay'] for r in rows), financed_fee=financed_fee,
                  house_scale=i.price+financed_fee, selected_position=closing['position'])
    if page == 4:
        return result
    layers = composition(i, plan)
    timeline = []
    with localcontext() as ctx:
        # Retain the exact existing component-reporting identity when splitting equity.
        ctx.prec = 150
        for row, components in zip(rows, layers):
            if row['month'] % 12 and row['month'] != month:
                continue
            timeline.append(dict(month=row['month'], opening_equity=opening['equity'],
                                 principal=row['equity']-opening['equity'], cash=components['cash'],
                                 day_one=components['day_one'], monthly=components['monthly'],
                                 position=row['position']))
        cash_growth = closing['cash'] - opening['cash'] - sum(r['cash_add'] for r in rows)
        investment_growth = closing['investment'] - opening['investment'] - closing['contributed']
        result.update(timeline=timeline, starting_money=i.total,
                      budget_used=i.monthly*month-closing['spent_total'], purchase_costs=i.costs,
                      product_fee=plan['product_fee'], cash_growth=cash_growth,
                      investment_growth=investment_growth)
    return result


@lru_cache(maxsize=1024)
def _position(i: m.Inputs, term: int, deposit: D, month: int, growth: D) -> dict:
    """Reprice only annual investment growth, with the original mortgage and allocation."""
    plan = m.project(replace(i, investment_return=growth), deposit.quantize(m.PENNY), term,
                     detailed=False, objective_month=month, through_month=month)
    return plan['rows'][0]


def _comparator(i: m.Inputs, term: int, deposit: D, month: int) -> D | None:
    regions = phone._regions(i, term, month)
    highest = max((b for _, b, _ in regions), default=None)
    if highest != deposit:
        return highest
    # At the maximum, show the opposite affordable end, including disconnected quotes.
    lowest = min((a for a, _, _ in regions), default=None)
    return lowest if lowest != deposit else None


@lru_cache(maxsize=32)
def _curve(i: m.Inputs, other: m.Inputs | None, term: int, deposit: D, other_deposit: D | None,
           month: int, low: D, high: D) -> tuple[list, list]:
    def point(growth: D) -> dict:
        selected = _position(i, term, deposit, month, growth)['position']
        alternative = _position(other, term, other_deposit, month, growth)['position'] if other else None
        return dict(growth=growth, selected=selected, other=alternative,
                    difference=selected-alternative if other else None)

    points = [point(low + (high-low)*n/GROWTH_INTERVALS) for n in range(GROWTH_INTERVALS+1)]
    crossings = []
    if other and any(p['difference'] for p in points):
        for n, a in enumerate(points):
            if a['difference'] == 0:
                # A whole coincident segment has no single crossing.
                left = points[n-1]['difference'] if n else None
                right = points[n+1]['difference'] if n+1 < len(points) else None
                if (left is None and right or right is None and left or left and right and left*right < 0):
                    crossings.append(dict(growth=a['growth'], low=a['growth'], high=a['growth'], position=a['selected']))
                continue
            if n+1 == len(points):
                continue
            b = points[n+1]
            if a['difference']*b['difference'] >= 0:
                continue
            while b['growth'] - a['growth'] > CROSSING_WIDTH:
                middle = point((a['growth']+b['growth'])/2)
                if middle['difference'] == 0:
                    a = b = middle
                    break
                if a['difference']*middle['difference'] < 0:
                    b = middle
                else:
                    a = middle
            root = point((a['growth']+b['growth'])/2)
            crossings.append(dict(growth=root['growth'], low=a['growth'], high=b['growth'], position=root['selected']))
    return points, crossings


def _sensitivity(i: m.Inputs, selected: dict, term: int, deposit: D, month: int, raw_growth: str | None) -> dict:
    low, high = min(GROWTH_LOW, i.investment_return), max(GROWTH_HIGH, i.investment_return)
    growth = i.investment_return if raw_growth is None else D(str(raw_growth))
    if not growth.is_finite() or len(growth.as_tuple().digits) > 16 or not low <= growth <= high:
        raise ValueError('Choose an investment growth rate on the displayed scale.')
    own = phone._choice_inputs(i,selected)
    other_deposit = _comparator(i,term,deposit,month)
    other = (phone._choice_inputs(i,phone._plan(i,term,other_deposit,month))
             if other_deposit is not None else None)
    points, crossings = _curve(own,other,term,deposit,other_deposit,month,low,high)
    current = _position(own,term,deposit,month,growth)
    alternative = _position(other,term,other_deposit,month,growth)['position'] if other else None
    return dict(low=low, high=high, growth=growth, other_deposit=other_deposit, points=points,
                crossings=crossings, selected_position=current['position'], other_position=alternative,
                difference=current['position']-alternative if other else None,
                fall_month=i.stress_month, recovery_months=i.recovery_months,
                cash=current['cash'], equity=current['equity'], investment=current['investment'],
                house_and_cash=current['equity']+current['cash'])


@m.fixed
def explore(i: m.Inputs, term: int, deposit: D, month: int, request: dict) -> dict:
    """Return the page's exact serializable GBP values at the chosen comparison month."""
    page = request['page']
    if page not in (4,5,6):
        raise ValueError('Choose an ownership page from 4 to 6.')
    selected = phone._plan(i, term, deposit, month)
    result = dict(version=VERSION, page=page, deposit=deposit, term_years=term, objective_month=month,
                  status=selected['status'], reason=selected['reason'], source=selected['source'])
    if selected['status'] == 'funded':
        if page == 6:
            result.update(_sensitivity(i, selected, term, deposit, month, request.get('growth')))
        else:
            result.update(_ownership(phone._choice_inputs(i,selected),term,deposit,month,page))
    return m.serial(result)
