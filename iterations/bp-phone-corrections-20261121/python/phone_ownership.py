"""Synthetic phone reports for borrowing costs, owned assets and return sensitivity."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D, localcontext
from functools import lru_cache

import model as m
import phone_provider as phone
from target_reporting import composition


VERSION = 'phone-ownership-2026-11-21-corrections-v1'
# Display domain for the synthetic tester. A household's entered rate always fits.
GROWTH_LOW = D('-.04')
GROWTH_HIGH = D('.12')
GROWTH_INTERVALS = 16
# A verified sign-changing bracket narrower than 0.001 percentage points.
CROSSING_WIDTH = D('.00001')
# Mirror the phone slider's GBP stops. Wider searches leave intermediate stops on demand.
DEPOSIT_STEP_GBP = D(500)
MAX_EAGER_BORROWING_STEPS = 160


@lru_cache(maxsize=8)
def _ledger(i: m.Inputs, term: int, deposit: D, month: int) -> dict:
    return m.project(i, deposit.quantize(m.PENNY), term, objective_month=month, through_month=month)


def _borrowed(i: m.Inputs, selected: dict) -> dict:
    """Expose the selected projection's mortgage ledger at the comparison date."""
    fee = selected['fee'] if selected.get('fee_mode') == 'loan' else m.ZERO
    return dict(deposit=selected['deposit'], status='funded', interest=selected['interest'],
                principal=selected['opening_debt']-selected['closing_debt'], still_owed=selected['closing_debt'],
                financed_fee=fee, house_scale=i.price+fee, selected_position=selected['position'])


@lru_cache(maxsize=12)
def _borrow_drag_reports(i: m.Inputs, term: int, month: int) -> dict:
    """Price a bounded set of exact slider positions when the borrowing page first opens."""
    # Always include priced edges and pins. Limit eager £500 stops for large households.
    regions = phone._regions(i, term, month)
    deposits = {d for lo, hi, _ in regions for d in (lo, hi)}
    step = DEPOSIT_STEP_GBP
    if sum((hi-lo)//step for lo, hi, _ in regions) <= MAX_EAGER_BORROWING_STEPS:
        for lo, hi, _ in regions:
            first = int(lo//step) + int(lo%step != 0)
            deposits.update(step*n for n in range(first, int(hi//step)+1))
    result = {}
    for d in sorted(deposits):
        selected = phone._plan(i, term, d, month)
        if selected['status'] == 'funded':
            result[str(d.quantize(m.PENNY))] = _borrowed(i, selected)
    return result


def _ownership(i: m.Inputs, term: int, deposit: D, month: int, page: int, selected: dict) -> dict:
    plan = _ledger(i, term, deposit, month)
    rows = plan['rows']
    opening, closing = rows[0], rows[-1]
    result = _borrowed(i, selected)
    result['overpaid'] = sum(r['overpay'] for r in rows)
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


def _above(difference: D | None, deposit: D, other_deposit: D) -> str | None:
    if not difference:
        return None
    return 'smaller' if (difference > 0) == (deposit < other_deposit) else 'larger'


def _tower(row: dict, plan: dict) -> dict:
    """Split a projected GBP position into house/cash, investment principal and signed growth."""
    with localcontext() as ctx:
        ctx.prec = 150
        paid_in = plan['opening_investment'] + row['contributed']
        growth = row['investment'] - paid_in
        # Read house and cash as the complement of the reported investment balance.
        # This retains the original position's 50-digit summation residue and exactly
        # reconciles its three layers, as in the existing component reporting contract.
        house_and_cash = row['position'] - row['investment']
        return dict(deposit=plan['deposit'], position=row['position'], house_and_cash=house_and_cash,
                    paid_in=paid_in, growth=growth)


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
                    crossings.append(dict(growth=a['growth'], low=a['growth'], high=a['growth'],
                                          position=a['selected'], above=_above(right, deposit, other_deposit)))
                continue
            if n+1 == len(points):
                continue
            b = points[n+1]
            if a['difference']*b['difference'] >= 0:
                continue
            above = _above(b['difference'], deposit, other_deposit)
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
            crossings.append(dict(growth=root['growth'], low=a['growth'], high=b['growth'], position=root['selected'], above=above))
    return points, crossings


def _growth_input(i: m.Inputs, raw_growth: str | None) -> tuple[D, D, D]:
    low, high = min(GROWTH_LOW, i.investment_return), max(GROWTH_HIGH, i.investment_return)
    growth = i.investment_return if raw_growth is None else D(str(raw_growth))
    if not growth.is_finite() or len(growth.as_tuple().digits) > 16 or not low <= growth <= high:
        raise ValueError('Choose an investment growth rate on the displayed scale.')
    return low, high, growth


def _growth_ranking(i: m.Inputs, term: int, deposit: D, month: int, growth: D, selected: dict) -> dict:
    from phone_futures import _rank, _compact
    preview = replace(i, investment_return=growth)
    leader, _, ties = _rank(preview, term, deposit, month, deposit)
    return dict(leader=_compact(leader), ties=ties, difference_to_term=phone._difference(leader,selected),
                terms_at_deposit=phone._terms_at_deposit(preview,deposit,month,selected))


def _sensitivity(i: m.Inputs, selected: dict, term: int, deposit: D, month: int, raw_growth: str | None) -> dict:
    low, high, growth = _growth_input(i, raw_growth)
    own = phone._choice_inputs(i,selected)
    other_deposit = _comparator(i,term,deposit,month)
    other_plan = phone._plan(i,term,other_deposit,month) if other_deposit is not None else None
    other = phone._choice_inputs(i,other_plan) if other_plan else None
    points, crossings = _curve(own,other,term,deposit,other_deposit,month,low,high)
    current = _position(own,term,deposit,month,growth)
    towers = [_tower(current, selected)]
    alternative = None
    if other is not None:
        other_row = _position(other,term,other_deposit,month,growth)
        towers.append(_tower(other_row, other_plan))
        alternative = other_row['position']
    ranking = _growth_ranking(i,term,deposit,month,growth,{**selected, 'position':current['position']})
    return dict(**ranking, towers=towers, low=low, high=high, growth=growth, other_deposit=other_deposit, points=points,
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
    selected = phone._preview_choice(i, term, deposit, month, request)
    result = dict(version=VERSION, page=page, deposit=deposit, term_years=term, objective_month=month,
                  status=selected['status'], reason=selected['reason'], source=selected['source'])
    if selected['status'] == 'funded':
        if page == 6:
            result.update(_sensitivity(i, selected, term, deposit, month, request.get('growth')))
        else:
            result.update(_ownership(phone._choice_inputs(i,selected),term,deposit,month,page,selected))
            if page == 4:
                result['drag_reports'] = _borrow_drag_reports(i,term,month)
    elif page == 6:
        _, _, growth = _growth_input(i, request.get('growth'))
        result.update(_growth_ranking(i,term,deposit,month,growth,selected))
    return m.serial(result)
